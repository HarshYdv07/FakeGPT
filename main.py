import sys
import os
import pyttsx3
import speech_recognition as sr
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLineEdit, QListWidget, QListWidgetItem, QInputDialog, QFileDialog
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextDocument
from PyQt5.QtPrintSupport import QPrinter
import google.generativeai as genai
from dotenv import load_dotenv
import json
import textwrap
import html

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel("models/gemini-1.5-pro")

engine = pyttsx3.init()
HISTORY_FILE = "chat_history.json"


class ListeningThread(QThread):
    recognized_text = pyqtSignal(str)

    def __init__(self, recognizer):
        super().__init__()
        self.recognizer = recognizer

    def run(self):
        with sr.Microphone() as source:
            try:
                audio = self.recognizer.listen(source, timeout=5)
                query = self.recognizer.recognize_google(audio)
                self.recognized_text.emit(query)
            except Exception as e:
                self.recognized_text.emit(f"Error: {str(e)}")


class TypingThread(QThread):
    update = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, full_text):
        super().__init__()
        self.full_text = full_text

    def run(self):
        content = ""
        for c in self.full_text:
            content += c
            self.update.emit(content)
            self.msleep(4)
        self.finished.emit()


class ChatApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FakeGPT")
        self.setGeometry(200, 100, 1000, 700)
        self.setStyleSheet("background-color: #121212; color: white;")

        self.chat_sessions = []
        self.current_session = []

        self.typing_thread = None
        self.copy_button = None
        self.latest_code = ""
        self.listening_mode = False

        self.init_ui()
        self.load_history()

        self.recognizer = sr.Recognizer()
        self.listening_thread = ListeningThread(self.recognizer)
        self.listening_thread.recognized_text.connect(self.handle_recognized_text)

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(250)
        self.sidebar.setStyleSheet("background-color: #1f1f1f;")
        sidebar_layout = QVBoxLayout(self.sidebar)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 Search history...")
        self.search_bar.setStyleSheet("padding: 8px; background-color: #2a2a2a; color: white; border: none;")
        self.search_bar.textChanged.connect(self.filter_history)
        sidebar_layout.addWidget(self.search_bar)

        self.history_list = QListWidget()
        self.history_list.setStyleSheet("background-color: #1f1f1f; color: white;")
        self.history_list.itemClicked.connect(self.load_history_item)
        self.history_list.itemDoubleClicked.connect(self.rename_history_item)
        sidebar_layout.addWidget(self.history_list)

        self.sidebar.setLayout(sidebar_layout)

        chat_area = QVBoxLayout()

        topbar = QHBoxLayout()
        self.sidebar_toggle_btn = QPushButton("☰")
        self.sidebar_toggle_btn.setFixedWidth(40)
        self.sidebar_toggle_btn.clicked.connect(self.toggle_sidebar)
        topbar.addWidget(self.sidebar_toggle_btn)

        new_chat_btn = QPushButton("🆕 New Chat")
        new_chat_btn.clicked.connect(self.new_chat)
        topbar.addWidget(new_chat_btn)

        export_btn = QPushButton("📄 Export PDF")
        export_btn.clicked.connect(self.export_chat_to_pdf)
        export_btn.setStyleSheet("background-color: #2a2a2a; color: white;")
        topbar.addWidget(export_btn)

        topbar.addStretch()
        listen_btn = QPushButton("🎙️ Listen")
        listen_btn.clicked.connect(self.start_listening)
        topbar.addWidget(listen_btn)

        for btn in [self.sidebar_toggle_btn, new_chat_btn, listen_btn]:
            btn.setStyleSheet("background-color: #2a2a2a; color: white;")

        chat_area.addLayout(topbar)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("background-color: #181818; color: white; font-size: 14px;")
        chat_area.addWidget(self.chat_display)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type your message...")
        self.input_field.setStyleSheet("background-color: #2a2a2a; color: white; padding: 10px;")
        self.input_field.returnPressed.connect(self.handle_text_input)
        chat_area.addWidget(self.input_field)

        main_layout.addWidget(self.sidebar)
        main_layout.addLayout(chat_area)
        self.setLayout(main_layout)

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def filter_history(self, text):
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def display_message(self, message, sender="user"):
        if sender == "user":
            align = "right"
            color = "#00ff99"
            self.chat_display.append(
                f'<p align="{align}" style="color: {color}; margin: 10px;">{html.escape(message)}</p>'
            )
        else:
            formatted = self.format_bot_response(message)
            self.chat_display.append(formatted)

    def handle_text_input(self):
        text = self.input_field.text().strip()
        if text:
            self.listening_mode = False
            self.input_field.clear()
            self.current_session.append({"role": "user", "parts": [text]})
            self.display_message(text, sender="user")
            self.fetch_response(text)

    def start_listening(self):
        self.input_field.hide()
        self.listening_mode = True
        self.display_message("🎤 Listening...", sender="bot")
        self.listening_thread.start()

    def handle_recognized_text(self, text):
        self.input_field.show()
        if text.startswith("Error:"):
            self.display_message(text, sender="bot")
        else:
            self.current_session.append({"role": "user", "parts": [text]})
            self.display_message(text, sender="user")
            self.fetch_response(text)

    def fetch_response(self, prompt):
        try:
            convo = model.start_chat(history=self.current_session)
            self.show_typing_indicator()
            response = convo.send_message(prompt)
            self.hide_typing_indicator()
            text = response.text.strip()
            self.current_session.append({"role": "model", "parts": [text]})
            self.animate_response(text)
            if self.listening_mode:
                self.speak_response(text)
            self.save_history()
        except Exception as e:
            self.display_message(f"[Error]: {str(e)}", sender="bot")

    def speak_response(self, text):
        engine.say(text)
        engine.runAndWait()

    def animate_response(self, text):
        self.typing_thread = TypingThread(text)
        self.typing_thread.update.connect(lambda chunk: self.chat_display.setHtml(self.format_bot_response(chunk)))
        self.typing_thread.finished.connect(self.show_copy_button)
        self.latest_code = text
        self.typing_thread.start()

    def format_bot_response(self, text):
        escaped = html.escape(text)
        if "```" in escaped:
            sections = escaped.split("```")
            html_parts = []
            for i, sec in enumerate(sections):
                if i % 2 == 0:
                    html_parts.append(f"<p style='margin:10px; color:white;'>{sec}</p>")
                else:
                    html_parts.append(f"<pre style='background:#1e1e1e; color:#00ff99; padding:10px;'><code>{sec}</code></pre>")
            return "".join(html_parts)
        else:
            wrapped = textwrap.fill(escaped, 80)
            return f"<p style='margin:10px; color:white;'>{wrapped}</p>"

    def new_chat(self):
        if self.current_session:
            self.chat_sessions.append(self.current_session)
            summary = self.current_session[0]["parts"][0][:30] + "..."
            self.history_list.addItem(summary)
        self.current_session = []
        self.chat_display.clear()
        self.input_field.clear()
        self.save_history()

    def save_history(self):
        all_sessions = self.chat_sessions.copy()
        if self.current_session:
            all_sessions.append(self.current_session)
        with open(HISTORY_FILE, "w") as f:
            json.dump({"sessions": all_sessions}, f, indent=2)

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r") as f:
                data = json.load(f)
                self.chat_sessions = data.get("sessions", [])
                self.history_list.clear()
                for session in self.chat_sessions:
                    if session:
                        summary = session[0]["parts"][0][:30] + "..."
                        self.history_list.addItem(summary)

    def load_history_item(self, item):
        index = self.history_list.row(item)
        if index < len(self.chat_sessions):
            session = self.chat_sessions[index]
            self.chat_display.clear()
            for message in session:
                self.display_message(message["parts"][0], sender=message["role"])

    def rename_history_item(self, item):
        index = self.history_list.row(item)
        new_title, ok = QInputDialog.getText(self, "Rename Chat", "Enter new name:", text=item.text())
        if ok and new_title:
            item.setText(new_title)
            if index < len(self.chat_sessions):
                self.chat_sessions[index][0]["parts"][0] = new_title
                self.save_history()

    def show_copy_button(self):
        if self.copy_button:
            self.copy_button.deleteLater()
        self.copy_button = QPushButton("Copy Code", self)
        self.copy_button.setStyleSheet("background-color: #2a2a2a; color: white;")
        self.copy_button.clicked.connect(self.copy_code_to_clipboard)
        self.copy_button.move(self.width() - 150, 100)
        self.copy_button.show()

    def copy_code_to_clipboard(self):
        try:
            code = self.latest_code.split("```")[1]
        except IndexError:
            code = self.latest_code
        os.system(f"echo '{code}' | pbcopy")

    def show_typing_indicator(self):
        self.chat_display.append(
            '<p align="left" style="color: #888; font-style: italic;">Gemini is typing...</p>'
        )

    def hide_typing_indicator(self):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.select(cursor.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()
        self.chat_display.setTextCursor(cursor)

    def export_chat_to_pdf(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save Chat as PDF", "chat.pdf", "PDF Files (*.pdf)")
        if filename:
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(filename)
            doc = QTextDocument()
            doc.setHtml(self.chat_display.toHtml())
            doc.print_(printer)

    def closeEvent(self, event):
        self.new_chat()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    chatbot = ChatApp()
    chatbot.show()
    sys.exit(app.exec_())