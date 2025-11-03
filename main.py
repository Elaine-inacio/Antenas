from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, StringProperty, ObjectProperty
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.lang import Builder
import os
from kivy.metrics import dp
import numpy as np # type: ignore
import matplotlib.pyplot as plt # type: ignore
from kivy.core.window import Window # Pode ser útil para ajustes futuros
from kivy.clock import Clock
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.utils import platform
import threading # Necessário para a thread de leitura Bluetooth

# =================================================================
# Permissões Android para Bluetooth (INÍCIO DO TRECHO NOVO)
# =================================================================
if platform == 'android':
    try:
        from android.permissions import request_permissions, Permission # type: ignore

        def pedir_permissoes_bluetooth():
            try:
                # BLUETOOTH_CONNECT é essencial para pareados
                # ACCESS_FINE_LOCATION (ou BLUETOOTH_SCAN) é necessário para scan/descoberta
                request_permissions([
                    Permission.BLUETOOTH_CONNECT,
                    Permission.ACCESS_FINE_LOCATION
                ])
                print("🔹 Permissões Bluetooth solicitadas.")
            except Exception as e:
                print(f"Erro ao pedir permissões: {e}")
    except ImportError:
        # Define uma função dummy caso a importação falhe (ex: ambiente de teste android sem permissões)
        def pedir_permissoes_bluetooth():
            print("Funções de permissão Android não disponíveis para chamada.")
else:
    # Define uma função dummy para plataformas não-Android (Desktop)
    def pedir_permissoes_bluetooth():
        pass

# === Importações Bluetooth (ANDROID) ===
# Elas só funcionarão quando o app for compilado para Android com pyjnius
try:
    from jnius import autoclass # type: ignore
    # Importa as classes Android necessárias
    BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
    BluetoothDevice = autoclass('android.bluetooth.BluetoothDevice')
    BluetoothSocket = autoclass('android.bluetooth.BluetoothSocket')
    UUID = autoclass('java.util.UUID')
    print("Pyjnius e classes Bluetooth importadas com sucesso.")
except ImportError:
    # Caso não esteja no Android (ex: Desktop)
    print("Pyjnius ou classes Bluetooth não disponíveis. Rodando no modo Desktop.")
    BluetoothAdapter = None
    BluetoothDevice = None
    BluetoothSocket = None
    UUID = None

# -----------------------------------------------------------------
# VARIÁVEIS GLOBAIS DE DADOS
# -----------------------------------------------------------------
angles_deg = []
powers = []
reference_power = None


# --- Variáveis de Conexão Bluetooth ---
BLUETOOTH_STATUS = StringProperty("Status: Desconectado.")
BLUETOOTH_DEVICE_NAME = "ESP32MotorControl" 
BLUETOOTH_UUID = "00001101-0000-1000-8000-00805F9B34FB" # UUID padrão SPP (Serial Port Profile)
bluetooth_socket = None # Objeto para a conexão Bluetooth

# --- Carregamento do KV ---
if os.path.exists('motor.kv'):Builder.load_file('motor.kv')


# -----------------------------------------------------------------
# CLASSES DE TELA
# -----------------------------------------------------------------
class BluetoothScreen(Screen, BoxLayout):
    # Propriedade para refletir o status na UI (será ligada no KV)
    bluetooth_status = StringProperty("Status: Desconectado.") # NOVA PROPRIEDADE
    
    # -----------------------------------------------------------------
    # MÉTODOS DE BLUETOOTH
    # -----------------------------------------------------------------
    def connect_bluetooth(self):
        """Busca o dispositivo pareado e tenta conectar."""
        
        # 1. Checa a plataforma e as dependências
        if platform != 'android' or BluetoothAdapter is None:
            message = "Bluetooth só funciona no Android."
            self.show_popup_message(message)
            return
            
        adapter = BluetoothAdapter.getDefaultAdapter()
        if not adapter or not adapter.isEnabled():
            message = "Bluetooth Desabilitado. Habilite nas Configurações."
            self.show_popup_message(message)
            return

        # 2. Busca o dispositivo
        self.bluetooth_status = "Status: Buscando Dispositivo..."
        target_device = None
        
        # Percorre a lista de dispositivos pareados
        for device in adapter.getBondedDevices().toArray():
            if device.getName() == BLUETOOTH_DEVICE_NAME:
                target_device = device
                break

        if target_device is None:
            message = f"Dispositivo '{BLUETOOTH_DEVICE_NAME}' não encontrado na lista de pareados."
            self.bluetooth_status = "Status: Dispositivo não encontrado."
            self.show_popup_message(message)
            return
        
        self.bluetooth_status = f"Status: Conectando a {BLUETOOTH_DEVICE_NAME}..."
        print(f"Tentando conectar a: {target_device.getAddress()}")

        # 3. Tenta conectar em uma nova thread
        # Usamos threading para evitar que a UI congele durante a conexão.
        connect_thread = threading.Thread(target=self._attempt_connection, args=(target_device,), daemon=True)
        connect_thread.start()


    def _attempt_connection(self, target_device):
        """Função que executa a tentativa de conexão (em uma thread separada)."""
        global bluetooth_socket

        # 1. Cria o UUID
        uuid_obj = UUID.fromString(BLUETOOTH_UUID)
        
        # 2. Tenta criar o socket
        try:
            # Cria um socket RFCOMM (Bluetooth Clássico)
            bluetooth_socket = target_device.createRfcommSocketToServiceRecord(uuid_obj)
        except Exception as e:
            message = f"ERRO ao criar socket: {e}"
            Clock.schedule_once(lambda dt: self.show_popup_message(message), 0)
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: Erro de Socket."), 0)
            print(message)
            return

        # 3. Tenta conectar o socket
        try:
            message = "Iniciando Conexão..."
            self.show_popup_message(message)
            bluetooth_socket.connect() # ESTE É O BLOQUEANTE
            
            # Conexão bem-sucedida
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: CONECTADO!"), 0)
            Clock.schedule_once(lambda dt: self.show_popup_message("Conexão Bluetooth Estabelecida com Sucesso!"), 0)
            
            # Ativa o botão de avançar (deve ser agendado para rodar na thread principal)
            Clock.schedule_once(lambda dt: setattr(self.manager.get_screen('motor_control').ids.control_button, 'disabled', False), 0)

            # ** INICIA A THREAD DE LEITURA (NOVA THREAD PARA RECEBIMENTO DE DADOS) **
            read_thread = threading.Thread(target=self.read_bluetooth_data, daemon=True)
            read_thread.start()
            print("Thread de leitura Bluetooth iniciada.")

        except Exception as e:
            # Erro de conexão (dispositivo não está pronto, fora do alcance, etc.)
            message = f"ERRO de Conexão. Tente Novamente ou Pareie o Dispositivo: {e}"
            Clock.schedule_once(lambda dt: self.show_popup_message(message), 0)
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: Falha na Conexão."), 0)
            print(message)
            try:
                bluetooth_socket.close()
            except:
                pass # Ignora erro de fechar socket
            bluetooth_socket = None
            
    # ** NOVA FUNÇÃO DE THREAD PARA LEITURA DE DADOS **
    def read_bluetooth_data(self):
        """Thread responsável por ler dados do socket Bluetooth."""
        global bluetooth_socket
        if bluetooth_socket is None:
            return

        print("Thread de Leitura Ativa...")
        
        try:
            input_stream = bluetooth_socket.getInputStream()
            buffer = bytearray()
            
            while bluetooth_socket is not None:
                # Loop de leitura de byte a byte (bloqueante)
                data = input_stream.read() 
                
                if data == -1: # Socket fechado
                    break
                
                char = chr(data)
                buffer.extend(char.encode('utf-8'))
                
                # Exemplo: Se o ESP32 envia dados terminados com '\n'
                if char == '\n':
                    full_message = buffer.decode('utf-8').strip()
                    print(f"DADO RECEBIDO: {full_message}")
                    # Limpa o buffer
                    buffer = bytearray()
                    
                    # Se precisar atualizar a UI com o dado recebido:
                    # Clock.schedule_once(lambda dt: self.manager.get_screen('motor_control').update_received_data(full_message), 0)

        except Exception as e:
            print(f"ERRO FATAL na thread de leitura Bluetooth: {e}")
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: Conexão Perdida."), 0)
            bluetooth_socket = None

    # -----------------------------------------------------------------
    # MÉTODOS DE TELA E UTILITÁRIOS
    # -----------------------------------------------------------------
    def go_to_motor_control(self):
        """Muda para a tela de controle do motor."""
        # Apenas permite avançar se estiver conectado (ou em modo desktop para testes)
        if bluetooth_socket is not None or platform != 'android':
            print("Mudando para tela de controle do motor...")
            self.manager.current = 'motor_control'
        else:
            self.show_popup_message("Conecte ao Bluetooth Primeiro!")


    def show_popup_message(self, message):
        """Exibe o popup de confirmação."""
        popup = ConfirmationPopup(message=message)
        popup.open()

class MotorControlScreen(Screen, BoxLayout):
    # Propriedades Kivy existentes
    posicao = NumericProperty(0)
    passo = NumericProperty(1) 
    pos_text = StringProperty("0°")

    # ** NOVAS PROPRIEDADES DE BLUETOOTH **
    last_slider_value = NumericProperty(0)# Último valor enviado pelo slider (para cálculo de diferença)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Inicializa o last_slider_value com a posição inicial
        self.last_slider_value = int(self.posicao) 
        self.atualizar_label()

    def atualizar_label(self, *args):
        self.pos_text = f"{int(self.posicao)}°"
        
    # ** NOVOS MÉTODOS DE BLUETOOTH **

    def _format_command(self, direction, step_value):
        """
        Formata o comando no padrão '&[D][PPP]', onde [D] é a direção (R/L) e [PPP] é o passo com 3 dígitos.
        Ex: ('R', 15) -> '&R015'
        Ex: ('L', 1)  -> '&L001'
        """
        # Garante que o passo seja um inteiro e formata com zeros à esquerda (03d)
        step_value = max(0, min(999, int(step_value))) # Limita o passo entre 0 e 999
        formatted_step = f"{step_value:03d}"
        command = f"&{direction}{formatted_step}"
        return command

    def send_bluetooth_data(self, data):
        """Envia dados via Bluetooth se o socket estiver ativo, ou simula no console."""
        global bluetooth_socket
        if bluetooth_socket is not None:
            try:
                # Envia os dados como bytes
                output_stream = bluetooth_socket.getOutputStream()
                output_stream.write(data.encode('utf-8'))
                output_stream.flush()
                print(f"ENVIADO VIA BLUETOOTH: {data}")
            except Exception as e:
                print(f"ERRO ao enviar dados via Bluetooth: {e}")
                # Avisa o usuário sobre a falha de envio
                self.manager.get_screen('bluetooth_connection').show_popup_message(f"ERRO DE ENVIO BT: {e}")
            except AttributeError:
                # Trata o caso do getOutputStream não existir (socket fechado)
                print("ERRO DE ENVIO: Socket Bluetooth está fechado ou inválido.")
        else:
            # Modo Desktop ou Desconectado
            print(f"MODO DESKTOP/DESCONECTADO: Comando simulado: {data}")

    def send_step_command(self, direction):
        """
        Envia o passo definido (self.passo) na direção especificada, respeitando os limites de 0° e 360°.
        Direção 'R' para '+', 'L' para '-'.
        """
        current_pos = self.posicao
        step = self.passo
        
        # CHECA LIMITES 0-360 ANTES DE ENVIAR COMANDO
        if direction == 'R':
            new_pos = min(360, current_pos + step)
        else: # direction == 'L'
            new_pos = max(0, current_pos - step)
            
        # Se a nova posição for igual à atual, significa que o limite foi atingido.
        if new_pos == current_pos:
            return 

        command = self._format_command(direction, self.passo)
        self.send_bluetooth_data(command)
        
        # Atualiza a posição da UI com o valor que já sabemos ser válido
        self.posicao = new_pos
        self.atualizar_label()
        
        # Após o passo ser enviado, atualiza o last_slider_value para ser consistente
        self.last_slider_value = int(self.posicao)


   # 3. Trata o botão 'Registrar Potencia'
    def register_power_command(self, potencia_input_ref, potencia_inserida_str):
        """
        Envia o passo definido (self.passo), sempre para a direita ('R'),
        e então adiciona a medida (lógica existente). O comando só é enviado 
        se um valor de potência válido for inserido E o limite de 360° não for excedido.
        """
        try:
            float(potencia_inserida_str)
            valor_valido = True
        except ValueError:
            valor_valido = False
        
        if valor_valido:
            new_pos = min(360, self.posicao + self.passo)
            if new_pos == self.posicao:
                message = f"Valor Máximo Atingido"
                popup = ConfirmationPopup(message=message)
                popup.open()
            command = self._format_command('R', self.passo)
            self.send_bluetooth_data(command)
            self.adicionar_medida_do_app(potencia_input_ref, self.posicao, potencia_inserida_str)
        else:
            message = f"Insira um Valor de Potência"
            popup = ConfirmationPopup(message=message)
            popup.open()


    # 4. Trata a mudança de posição no Slider (idealmente ao soltar o dedo)
    def on_slider_touch_up(self):
        """
        Calcula a diferença de posição do slider e envia o comando '&R/L<diff>'.
        """
        # Usamos self.posicao pois o slider_moved já a atualizou
        new_value = int(self.posicao) 
        
        # Calcula a diferença absoluta (o passo a ser enviado)
        diff = abs(new_value - self.last_slider_value)
        
        if diff == 0:
            print("Posição do slider não mudou. Nenhum comando enviado.")
            return

        # Determina a direção
        if new_value > self.last_slider_value:
            # Aumentou: Direita ('R')
            direction = 'R'
        else:
            # Diminuiu: Esquerda ('L')
            direction = 'L'

        # Formata e envia o comando com a diferença calculada
        command = self._format_command(direction, diff)
        self.send_bluetooth_data(command)
        
        # IMPORTANTE: Atualiza o último valor salvo APÓS o envio do comando
        self.last_slider_value = new_value
        print(f"Nova posição registrada (last_slider_value): {self.last_slider_value}. Comando enviado: {command}")
        
    # --- Funções de Movimento de UI (Mantidas) ---
    def aumentar(self):
        self.posicao = min(360, self.posicao + self.passo)
        self.atualizar_label()

    def diminuir(self):
        self.posicao = max(0, self.posicao - self.passo)
        self.atualizar_label()

    def slider_moved(self, widget):
        self.posicao = int(widget.value)
        self.atualizar_label()

    def definir_passo(self, valor):
        try:
            new_passo = int(valor)
            if 0 <= new_passo <= 999:
                 self.passo = new_passo
                 print(f"Novo valor de passo definido: {self.passo}")
            else:
                print("ERRO: Passo deve ser um valor inteiro entre 0 e 999.")
        except ValueError:
            print("ERRO: Valor de Passo inválido. Digite apenas números.")
        
    # --- Funções de Plotagem e Dados ---

    def adicionar_medida_do_app(self, potencia_input_ref, posicao_em_graus, potencia_inserida_str):
        try:
            # 1. Tenta converter a string para float
            potencia = float(potencia_inserida_str)
        except ValueError:
            Clock.schedule_once(lambda dt: potencia_input_ref.focus == True, 0.05)
            return

        angulo = int(posicao_em_graus)
        
        # 2. Adiciona ou Atualiza a medida
        if angulo not in angles_deg:
            angles_deg.append(angulo)
            powers.append(potencia)
            print(f"➡️ Medida adicionada: Ângulo {angulo}° -> Potência {potencia} dBm")
        else:
            index = angles_deg.index(angulo)
            powers[index] = potencia
            print(f"🔄 Medida atualizada: Ângulo {angulo}° -> Potência {potencia} dBm")
        
        # 3. Adiciona Passo (Movimento interno após adicionar medida)
        self.posicao = min(360, self.posicao + self.passo)
        self.atualizar_label()
        
        # ** NOVO: Atualiza o último valor após o movimento interno **
        self.last_slider_value = int(self.posicao)
        
        # 4. LIMPA O TEXTO E REQUER FOCO USANDO O CLOCK
        potencia_input_ref.text = '' # Limpa o campo
        Clock.schedule_once(lambda dt: self.set_focus_on_input(potencia_input_ref), 0.05)
    
    # Função auxiliar para redefinir o foco
    def set_focus_on_input(self, input_widget):
        """Função auxiliar para redefinir o foco de forma robusta."""
        input_widget.focus = True

    # Função chamada pelo botão "FINALIZAR"
    def go_to_save_screen(self):
        """Prepara o plot e navega para a tela de salvamento.
            Normaliza em relação à potência máxima."""
        
        global reference_power
        
        # 1. Verificação de dados
        if len(powers) < 1:
            print("⚠️ Adicione ao menos uma medida de potência para salvar.")
            return

        # 2. **Cálculo da Potência de Referência (Potência Máxima)**
        reference_power = np.max(powers)

        # 3. Preparação dos dados
        angles_np = np.array(angles_deg)
        powers_np = np.array(powers)
    
        if 0 not in angles_np:
            pass 

        angles_rad = np.deg2rad(angles_np)
        
        # CÁLCULO DO GANHO NORMALIZADO (em relação à Potência Máxima)
        gains_dB = powers_np - reference_power
        sorted_indices = np.argsort(angles_rad)
        angles_rad = angles_rad[sorted_indices]
        gains_dB = gains_dB[sorted_indices]

        # Fecha o loop no gráfico polar
        angles_rad = np.append(angles_rad, angles_rad[0])
        gains_dB = np.append(gains_dB, gains_dB[0])

        # 4. Configuração dos Limites Radiais
        min_gain = int(np.floor(np.min(gains_dB) / 5) * 5)
        max_gain = 0 

        # 5. Criação da Figura (Sem plt.show())
        plt.figure(figsize=(8, 8))
        ax = plt.subplot(111, polar=True)
        ax.plot(angles_rad, gains_dB, marker='o', color='#087e9e')
        ax.fill(angles_rad, gains_dB, alpha=0.2, color='#087e9e')
        
        ax.set_title("Diagrama de Radiação Normalizado (Graus X Potência em dBm)", va='bottom', y=1.1)
        
        ax.set_theta_zero_location('S')
        ax.set_theta_direction(-1)
        ax.set_rlabel_position(135)
        ax.set_rlim(min_gain, max_gain)
        ax.set_rticks(np.arange(min_gain, max_gain + 1, 5))
        ax.grid(True)
        
        # 6. Navega para a tela de salvamento
        self.manager.current = 'save_file_screen'

    def _perform_save(self, path, filename):
        """Salva a figura (obtida via plt.gcf()) no caminho e nome de arquivo especificados."""
        try:
            # Tenta obter a figura que foi criada na função go_to_save_screen
            fig = plt.gcf()
            
            # Garante que o nome do arquivo tenha uma extensão
            if not filename.lower().endswith(('.png', '.pdf')):
                filename = f"{filename}.png"
                
            filepath = os.path.join(path, filename)
            
            file_format = filepath.split('.')[-1]
            
            # Salva o arquivo. Usa dpi=300 para PNG.
            fig.savefig(filepath, format=file_format, dpi=300 if file_format == 'png' else None)
            
            message = f"Arquivo Salvo com sucesso em:\n{filepath}"
            popup = ConfirmationPopup(message=message)
            popup.open()
            
            # Fechar a figura (CRÍTICO para Matplotlib funcionar corretamente em apps)
            plt.close(fig)
            
        except Exception as e:
            message = f"ERRO ao salvar o arquivo. Tente novamente ou verifique as permissões: {e}"
            popup = ConfirmationPopup(message=message)
            popup.open()
            
        # Volta para a tela de controle do motor, independentemente do sucesso
        self.manager.current = 'motor_control'

    # RESETAR DADOS E ESTADO 
    def iniciar_novo_grafico(self):
        """Limpa todos os dados globais e reseta a posição para começar um novo gráfico."""
        global angles_deg, powers, reference_power
        
        # === 0. CAPTURA A POSIÇÃO ATUAL (passos para voltar a 0) ===
        # Ex: Se self.posicao = 100, steps_to_zero = 100.
        steps_to_zero = int(self.posicao)
        
        # 1. Limpa os dados globais
        angles_deg = []
        powers = []
        reference_power = None # Reseta a potência de referência
        
        # 2. Reseta a posição no Kivy e o last_slider_value
        self.posicao = 0
        self.last_slider_value = 0
        self.atualizar_label()
        
        # 3. ENVIA COMANDO BLUETOOTH PARA ZERAR O MOTOR FÍSICO
        if steps_to_zero > 0:
            # Move para a esquerda ('L') a quantidade de passos necessária para chegar a 0
            # Ex: Se steps_to_zero = 100, o comando enviado será &L100
            command = self._format_command('L', steps_to_zero)
            self.send_bluetooth_data(command)
        else:
            print("Motor já estava em 0. Nenhum comando de zeramento enviado.")
        
        # 4. Informa o usuário
        message = f"       NOVO GRÁFICO INICIADO:\nDados de Potência e Ângulo Limpos."
        popup = ConfirmationPopup(message=message)
        popup.open()

        
# -----------------------------------------------------------------
# CLASSE DE TELA DE SALVAMENTO
# -----------------------------------------------------------------
class SaveScreen(Screen, BoxLayout):
    """Tela para selecionar o local e nome do arquivo de salvamento."""
    
    # Propriedades para controle do FileChooser e nome
    path = StringProperty(os.getcwd())
    filename_text = StringProperty("Diagrama_Radiacao.png")
    
    def save_file(self, path, filename):
        """Chama a função real de salvamento na tela MotorControlScreen."""
        
        if not filename:
            message = f"Nome do arquivo não pode ser vazio."
            popup = ConfirmationPopup(message=message)
            popup.open()
            return
            
        # Chama a função de salvamento real na tela anterior
        self.manager.get_screen('motor_control')._perform_save(path, filename)

# -----------------------------------------------------------------
# CLASSES AUXILIARES
# -----------------------------------------------------------------
class ConfirmationPopup(Popup):
    """Popup simples para mostrar mensagens de confirmação."""
    def __init__(self, message, **kwargs):
        super().__init__(**kwargs)
        self.title = 'AVISO'
        self.size_hint = (0.7, 0.25)
        self.auto_dismiss = True # Fecha ao clicar fora
        self.content = Label(text=message, halign='center')
        
        # Opcional: agenda o fechamento automático após 4 segundos
        Clock.schedule_once(self.dismiss, 4)


# -----------------------------------------------------------------
# CLASSE PRINCIPAL DO APP
# -----------------------------------------------------------------
class MotorApp(App):
    def build(self):
        self.title = "Controle de Motor Stepper"
        
        sm = ScreenManager()

        bluetooth_screen = BluetoothScreen(name='bluetooth_connection')
        motor_control_screen = MotorControlScreen(name='motor_control')
        save_screen = SaveScreen(name='save_file_screen')
        
        sm.add_widget(bluetooth_screen)
        sm.add_widget(motor_control_screen)
        sm.add_widget(save_screen)
        
        sm.current = 'bluetooth_connection'

        return sm


if __name__ == "__main__":
    pedir_permissoes_bluetooth() 

    MotorControlScreen.passo.defaultvalue = 1
    MotorApp().run()