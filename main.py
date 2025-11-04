from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, StringProperty, ObjectProperty, ListProperty
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.lang import Builder
import os
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.utils import platform
from kivy.graphics import Color, Line, Ellipse, Rectangle
from kivy.uix.widget import Widget
import threading
import math
import json

# =================================================================
# Permissões Android para Bluetooth
# =================================================================
if platform == 'android':
    try:
        from android.permissions import request_permissions, Permission
        from android.storage import primary_external_storage_path

        def pedir_permissoes_bluetooth():
            try:
                request_permissions([
                    Permission.BLUETOOTH_CONNECT,
                    Permission.BLUETOOTH,
                    Permission.BLUETOOTH_ADMIN,
                    Permission.BLUETOOTH_SCAN,
                    Permission.ACCESS_FINE_LOCATION,
                    Permission.ACCESS_COARSE_LOCATION,
                    Permission.WRITE_EXTERNAL_STORAGE,
                    Permission.READ_EXTERNAL_STORAGE
                ])
                print("🔹 Permissões solicitadas.")
            except Exception as e:
                print(f"Erro ao pedir permissões: {e}")
    except ImportError:
        def pedir_permissoes_bluetooth():
            print("Funções de permissão Android não disponíveis.")
        def primary_external_storage_path():
            return "/sdcard"
else:
    def pedir_permissoes_bluetooth():
        pass
    def primary_external_storage_path():
        return os.path.expanduser("~")

# === Importações Bluetooth (ANDROID) ===
try:
    from jnius import autoclass
    BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
    BluetoothDevice = autoclass('android.bluetooth.BluetoothDevice')
    BluetoothSocket = autoclass('android.bluetooth.BluetoothSocket')
    UUID = autoclass('java.util.UUID')
    print("Pyjnius e classes Bluetooth importadas com sucesso.")
except ImportError:
    print("Pyjnius não disponível. Rodando no modo Desktop.")
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
BLUETOOTH_UUID = "00001101-0000-1000-8000-00805F9B34FB"
bluetooth_socket = None

# --- Carregamento do KV ---
if os.path.exists('motor.kv'):
    Builder.load_file('motor.kv')


# -----------------------------------------------------------------
# WIDGET PERSONALIZADO PARA PLOTAGEM POLAR
# -----------------------------------------------------------------
class PolarPlotWidget(Widget):
    """Widget personalizado que desenha um gráfico polar usando Kivy Graphics"""
    
    angles = ListProperty([])
    powers = ListProperty([])
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.update_plot, size=self.update_plot)
        self.bind(angles=self.update_plot, powers=self.update_plot)
    
    def update_plot(self, *args):
        """Desenha o gráfico polar"""
        self.canvas.clear()
        
        if len(self.angles) < 2 or len(self.powers) < 2:
            return
        
        with self.canvas:
            # Fundo
            Color(0.09, 0.10, 0.12, 1)
            Rectangle(pos=self.pos, size=self.size)
            
            # Configurações
            center_x = self.x + self.width / 2
            center_y = self.y + self.height / 2
            radius = min(self.width, self.height) * 0.35
            
            # Normaliza os dados
            max_power = max(self.powers) if self.powers else 1
            min_power = min(self.powers) if self.powers else 0
            power_range = max_power - min_power if max_power != min_power else 1
            
            # Círculos de grade (3 círculos)
            Color(0.3, 0.3, 0.3, 0.5)
            for i in range(1, 4):
                r = radius * i / 3
                Ellipse(pos=(center_x - r, center_y - r), size=(r * 2, r * 2))
            
            # Linhas radiais (12 linhas - a cada 30°)
            Color(0.3, 0.3, 0.3, 0.5)
            for angle in range(0, 360, 30):
                rad = math.radians(angle)
                x_end = center_x + radius * math.cos(rad)
                y_end = center_y + radius * math.sin(rad)
                Line(points=[center_x, center_y, x_end, y_end], width=1)
            
            # Prepara os pontos para plotagem
            points = []
            for i, angle in enumerate(self.angles):
                # Normaliza a potência (0 a 1)
                normalized = (self.powers[i] - min_power) / power_range
                r = radius * normalized
                
                # Converte ângulo (0° = Sul, sentido horário)
                # Kivy: 0° = Leste, sentido anti-horário
                rad = math.radians(90 - angle)
                
                x = center_x + r * math.cos(rad)
                y = center_y + r * math.sin(rad)
                points.extend([x, y])
            
            # Fecha o loop adicionando o primeiro ponto no final
            if len(points) >= 4:
                points.extend(points[0:2])
                
                # Desenha a área preenchida
                Color(0.03, 0.48, 0.64, 0.3)
                # Para preencher, precisamos triangular - simplificado aqui
                
                # Desenha a linha
                Color(0.03, 0.48, 0.64, 1)
                Line(points=points, width=2, close=True)
                
                # Desenha os pontos
                Color(1, 1, 1, 1)
                for i in range(0, len(points) - 2, 2):
                    Ellipse(pos=(points[i] - 3, points[i + 1] - 3), size=(6, 6))


# -----------------------------------------------------------------
# CLASSES DE TELA
# -----------------------------------------------------------------
class BluetoothScreen(Screen, BoxLayout):
    bluetooth_status = StringProperty("Status: Desconectado.")
    
    def connect_bluetooth(self):
        """Busca o dispositivo pareado e tenta conectar."""
        
        if platform != 'android' or BluetoothAdapter is None:
            message = "Bluetooth só funciona no Android."
            self.show_popup_message(message)
            return
            
        adapter = BluetoothAdapter.getDefaultAdapter()
        if not adapter or not adapter.isEnabled():
            message = "Bluetooth Desabilitado. Habilite nas Configurações."
            self.show_popup_message(message)
            return

        self.bluetooth_status = "Status: Buscando Dispositivo..."
        target_device = None
        
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

        connect_thread = threading.Thread(target=self._attempt_connection, args=(target_device,), daemon=True)
        connect_thread.start()

    def _attempt_connection(self, target_device):
        """Função que executa a tentativa de conexão (em uma thread separada)."""
        global bluetooth_socket

        uuid_obj = UUID.fromString(BLUETOOTH_UUID)
        
        try:
            bluetooth_socket = target_device.createRfcommSocketToServiceRecord(uuid_obj)
        except Exception as e:
            message = f"ERRO ao criar socket: {e}"
            Clock.schedule_once(lambda dt: self.show_popup_message(message), 0)
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: Erro de Socket."), 0)
            print(message)
            return

        try:
            message = "Iniciando Conexão..."
            Clock.schedule_once(lambda dt: self.show_popup_message(message), 0)
            bluetooth_socket.connect()
            
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: CONECTADO!"), 0)
            Clock.schedule_once(lambda dt: self.show_popup_message("Conexão Bluetooth Estabelecida com Sucesso!"), 0)
            
            Clock.schedule_once(lambda dt: setattr(self.manager.get_screen('motor_control').ids.control_button, 'disabled', False), 0)

            read_thread = threading.Thread(target=self.read_bluetooth_data, daemon=True)
            read_thread.start()
            print("Thread de leitura Bluetooth iniciada.")

        except Exception as e:
            message = f"ERRO de Conexão: {e}"
            Clock.schedule_once(lambda dt: self.show_popup_message(message), 0)
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: Falha na Conexão."), 0)
            print(message)
            try:
                bluetooth_socket.close()
            except:
                pass
            bluetooth_socket = None
            
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
                data = input_stream.read()
                
                if data == -1:
                    break
                
                char = chr(data)
                buffer.extend(char.encode('utf-8'))
                
                if char == '\n':
                    full_message = buffer.decode('utf-8').strip()
                    print(f"DADO RECEBIDO: {full_message}")
                    buffer = bytearray()

        except Exception as e:
            print(f"ERRO na thread de leitura Bluetooth: {e}")
            Clock.schedule_once(lambda dt: setattr(self, 'bluetooth_status', "Status: Conexão Perdida."), 0)
            bluetooth_socket = None

    def go_to_motor_control(self):
        """Muda para a tela de controle do motor."""
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
    posicao = NumericProperty(0)
    passo = NumericProperty(1)
    pos_text = StringProperty("0°")
    last_slider_value = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_slider_value = int(self.posicao)
        self.atualizar_label()

    def atualizar_label(self, *args):
        self.pos_text = f"{int(self.posicao)}°"
        
    def _format_command(self, direction, step_value):
        """Formata o comando no padrão '&[D][PPP]'"""
        step_value = max(0, min(999, int(step_value)))
        formatted_step = f"{step_value:03d}"
        command = f"&{direction}{formatted_step}"
        return command

    def send_bluetooth_data(self, data):
        """Envia dados via Bluetooth se o socket estiver ativo."""
        global bluetooth_socket
        if bluetooth_socket is not None:
            try:
                output_stream = bluetooth_socket.getOutputStream()
                output_stream.write(data.encode('utf-8'))
                output_stream.flush()
                print(f"ENVIADO VIA BLUETOOTH: {data}")
            except Exception as e:
                print(f"ERRO ao enviar dados via Bluetooth: {e}")
                self.manager.get_screen('bluetooth_connection').show_popup_message(f"ERRO DE ENVIO BT: {e}")
        else:
            print(f"MODO DESKTOP/DESCONECTADO: Comando simulado: {data}")

    def send_step_command(self, direction):
        """Envia o passo definido na direção especificada."""
        current_pos = self.posicao
        step = self.passo
        
        if direction == 'R':
            new_pos = min(360, current_pos + step)
        else:
            new_pos = max(0, current_pos - step)
            
        if new_pos == current_pos:
            return 

        command = self._format_command(direction, self.passo)
        self.send_bluetooth_data(command)
        
        self.posicao = new_pos
        self.atualizar_label()
        self.last_slider_value = int(self.posicao)

    def register_power_command(self, potencia_input_ref, potencia_inserida_str):
        """Registra potência e move motor."""
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
                return
            command = self._format_command('R', self.passo)
            self.send_bluetooth_data(command)
            self.adicionar_medida_do_app(potencia_input_ref, self.posicao, potencia_inserida_str)
        else:
            message = f"Insira um Valor de Potência"
            popup = ConfirmationPopup(message=message)
            popup.open()

    def on_slider_touch_up(self):
        """Calcula a diferença de posição do slider e envia o comando."""
        new_value = int(self.posicao)
        diff = abs(new_value - self.last_slider_value)
        
        if diff == 0:
            return

        direction = 'R' if new_value > self.last_slider_value else 'L'
        command = self._format_command(direction, diff)
        self.send_bluetooth_data(command)
        self.last_slider_value = new_value
        
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
            print("ERRO: Valor de Passo inválido.")
        
    def adicionar_medida_do_app(self, potencia_input_ref, posicao_em_graus, potencia_inserida_str):
        try:
            potencia = float(potencia_inserida_str)
        except ValueError:
            Clock.schedule_once(lambda dt: setattr(potencia_input_ref, 'focus', True), 0.05)
            return

        angulo = int(posicao_em_graus)
        
        if angulo not in angles_deg:
            angles_deg.append(angulo)
            powers.append(potencia)
            print(f"➡️ Medida adicionada: Ângulo {angulo}° -> Potência {potencia} dBm")
        else:
            index = angles_deg.index(angulo)
            powers[index] = potencia
            print(f"🔄 Medida atualizada: Ângulo {angulo}° -> Potência {potencia} dBm")
        
        self.posicao = min(360, self.posicao + self.passo)
        self.atualizar_label()
        self.last_slider_value = int(self.posicao)
        
        potencia_input_ref.text = ''
        Clock.schedule_once(lambda dt: self.set_focus_on_input(potencia_input_ref), 0.05)
    
    def set_focus_on_input(self, input_widget):
        """Função auxiliar para redefinir o foco."""
        input_widget.focus = True

    def go_to_save_screen(self):
        """Prepara os dados e navega para a tela de visualização."""
        global reference_power
        
        if len(powers) < 1:
            print("⚠️ Adicione ao menos uma medida de potência.")
            message = "Adicione ao menos uma medida!"
            popup = ConfirmationPopup(message=message)
            popup.open()
            return

        reference_power = max(powers)
        
        # Passa os dados para a tela de visualização
        save_screen = self.manager.get_screen('save_file_screen')
        save_screen.prepare_plot_data(angles_deg.copy(), powers.copy(), reference_power)
        
        self.manager.current = 'save_file_screen'

    def iniciar_novo_grafico(self):
        """Limpa todos os dados globais e reseta a posição."""
        global angles_deg, powers, reference_power
        
        steps_to_zero = int(self.posicao)
        
        angles_deg = []
        powers = []
        reference_power = None
        
        self.posicao = 0
        self.last_slider_value = 0
        self.atualizar_label()
        
        if steps_to_zero > 0:
            command = self._format_command('L', steps_to_zero)
            self.send_bluetooth_data(command)
        
        message = "NOVO GRÁFICO INICIADO:\nDados Limpos."
        popup = ConfirmationPopup(message=message)
        popup.open()


# -----------------------------------------------------------------
# CLASSE DE TELA DE SALVAMENTO
# -----------------------------------------------------------------
class SaveScreen(Screen, BoxLayout):
    """Tela para visualizar o gráfico e salvar."""
    
    path = StringProperty("")
    filename_text = StringProperty("Diagrama_Radiacao.json")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Define o caminho padrão
        if platform == 'android':
            self.path = os.path.join(primary_external_storage_path(), 'Documents')
        else:
            self.path = os.path.expanduser("~/Documents")
    
    def prepare_plot_data(self, angles, powers, ref_power):
        """Prepara os dados para plotagem."""
        # Normaliza as potências
        gains_dB = [p - ref_power for p in powers]
        
        # Ordena por ângulo
        sorted_data = sorted(zip(angles, gains_dB))
        sorted_angles = [d[0] for d in sorted_data]
        sorted_gains = [d[1] for d in sorted_data]
        
        # Atualiza o widget de plotagem
        if hasattr(self.ids, 'polar_plot'):
            self.ids.polar_plot.angles = sorted_angles
            self.ids.polar_plot.powers = sorted_gains
    
    def save_file(self, path, filename):
        """Salva os dados em formato JSON."""
        global angles_deg, powers, reference_power
        
        if not filename:
            message = "Nome do arquivo não pode ser vazio."
            popup = ConfirmationPopup(message=message)
            popup.open()
            return
        
        # Garante extensão .json
        if not filename.lower().endswith('.json'):
            filename = f"{filename}.json"
        
        try:
            filepath = os.path.join(path, filename)
            
            # Prepara os dados para salvar
            data_to_save = {
                'angles_deg': angles_deg,
                'powers_dBm': powers,
                'reference_power': reference_power,
                'gains_dB': [p - reference_power for p in powers] if reference_power else powers
            }
            
            # Salva em JSON
            with open(filepath, 'w') as f:
                json.dump(data_to_save, f, indent=2)
            
            message = f"Dados salvos em:\n{filepath}"
            popup = ConfirmationPopup(message=message)
            popup.open()
            
        except Exception as e:
            message = f"ERRO ao salvar: {e}"
            popup = ConfirmationPopup(message=message)
            popup.open()
        
        # Volta para a tela de controle
        Clock.schedule_once(lambda dt: setattr(self.manager, 'current', 'motor_control'), 1.5)


# -----------------------------------------------------------------
# CLASSES AUXILIARES
# -----------------------------------------------------------------
class ConfirmationPopup(Popup):
    """Popup simples para mostrar mensagens de confirmação."""
    def __init__(self, message, **kwargs):
        super().__init__(**kwargs)
        self.title = 'AVISO'
        self.size_hint = (0.7, 0.25)
        self.auto_dismiss = True
        self.content = Label(text=message, halign='center')
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
