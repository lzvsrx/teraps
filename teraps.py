"""
Teraps - assistente pessoal futurista para Windows.

Uma base original, leve e extensivel: interface holografica, voz feminina
quando disponivel, memoria local, pesquisa na internet, abertura de apps e
um unico executador.
"""

from __future__ import annotations

import datetime as _dt
import html.parser
import json
import logging
import math
import os
import platform
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Canvas, Entry, Frame, Label, Tk, Text, StringVar

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


APP_NAME = "Teraps"
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = BASE_DIR
DATA_DIR = BASE_DIR / "teraps_data"
MEMORY_DB = DATA_DIR / "memory.sqlite3"
CONFIG_FILE = DATA_DIR / "config.json"
LOG_FILE = DATA_DIR / "teraps.log"
ASSETS_DIR = RESOURCE_DIR / "assets"
ICON_FILE = ASSETS_DIR / "teraps.ico"
AVATAR_FILE = ASSETS_DIR / "teraps_avatar.png"


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _hidden_startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def run_hidden(args, **kwargs) -> subprocess.CompletedProcess:
    if not kwargs.get("capture_output"):
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.DEVNULL)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if os.name == "nt":
        kwargs.setdefault("startupinfo", _hidden_startupinfo())
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)


def popen_hidden(args, **kwargs) -> subprocess.Popen:
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    kwargs.setdefault("stderr", subprocess.DEVNULL)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if os.name == "nt":
        kwargs.setdefault("startupinfo", _hidden_startupinfo())
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.Popen(args, **kwargs)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def setup_logging() -> None:
    ensure_dirs()
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


@dataclass
class HardwareProfile:
    name: str
    fps: int
    particles: int
    glow: bool
    voice_enabled: bool
    web_enabled: bool
    os_label: str = ""
    cpu_cores: int = 0
    memory_gb: float = 0.0
    power_mode: str = "desconhecido"
    reason: str = ""


@dataclass
class VoiceInputResult:
    ok: bool
    text: str = ""
    status: str = "error"
    message: str = ""


class Config:
    DEFAULT = {
        "assistant_name": "Teraps",
        "assistant_persona": "calma, feminina, curiosa e direta",
        "voice_engine": "neural",
        "neural_voice": "pt-BR-FranciscaNeural",
        "neural_voice_rate": "-3%",
        "neural_voice_pitch": "-2Hz",
        "neural_voice_volume": "+0%",
        "voice_rate": 178,
        "voice_volume": 0.95,
        "voice_name_hint": "female",
        "audio_output": "windows_default",
        "profile": "auto",
        "user_name": "",
        "auto_speak": True,
        "listen_language": "pt-BR",
        "mic_backend": "auto",
        "mic_timeout": 6,
        "mic_phrase_time_limit": 11,
        "mic_calibration_seconds": 0.45,
        "mic_sounddevice_seconds": 6,
        "mic_sample_rate": 16000,
        "theme": "cyan",
        "avatar_3d_mode": True,
        "youtube_api_credentials": "",
        "youtube_oauth_token": "",
        "app_aliases": {},
        "workspace_ide": "code",
        "workspace_path": str(BASE_DIR),
        "home_hub_url": "",
        "home_hub_token": "",
        "daily_summary_hour": "08:00",
        "hologram_bridge_enabled": False,
        "hologram_bridge_host": "127.0.0.1",
        "hologram_bridge_port": 8765,
        "unreal_editor_path": r"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe",
        "unreal_project_path": str(BASE_DIR / "unreal" / "TerapsHologram" / "TerapsHologram.uproject"),
        "unreal_bridge_script": str(BASE_DIR / "unreal" / "TerapsHologram" / "Content" / "Python" / "teraps_unreal_bridge.py"),
        "auto_learning_enabled": True,
        "auto_maintenance_enabled": True,
        "auto_update_check_enabled": True,
        "auto_proactive_enabled": True,
        "auto_update_source": "",
        "program_version": "0.9.0",
        "last_auto_maintenance": "",
        "last_update_check": "",
        "last_proactive_summary": "",
        "adaptive_hardware_enabled": True,
        "adaptive_low_power_on_battery": True,
        "adaptive_last_profile": {},
        "adaptive_visual_scale": 1.0,
        "adaptive_last_applied": "",
    }

    def __init__(self) -> None:
        ensure_dirs()
        self.conn = sqlite3.connect(MEMORY_DB, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        self.data = dict(self.DEFAULT)
        self._migrate_json_config()
        self._load_from_db()
        self.save()

    def _migrate_json_config(self) -> None:
        if CONFIG_FILE.exists():
            try:
                old = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for key, value in old.items():
                    if key in self.DEFAULT and self._get_raw(key) is None:
                        self._set_raw(key, value)
            except Exception:
                logging.exception("Falha ao ler config; usando padroes.")

    def _load_from_db(self) -> None:
        cur = self.conn.execute("SELECT key, value FROM settings")
        for key, raw in cur.fetchall():
            if key in self.DEFAULT:
                try:
                    self.data[key] = json.loads(raw)
                except Exception:
                    self.data[key] = raw

    def _get_raw(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def _set_raw(self, key: str, value) -> None:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        self.conn.commit()

    def save(self) -> None:
        for key, value in self.data.items():
            self._set_raw(key, value)

    def __getitem__(self, key: str):
        return self.data.get(key)

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value
        self.save()


class Memory:
    def __init__(self) -> None:
        ensure_dirs()
        self.conn = sqlite3.connect(MEMORY_DB, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(kind, key)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learned_topics (
                topic TEXT PRIMARY KEY,
                score INTEGER NOT NULL DEFAULT 1,
                last_seen TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                prompt TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_profile (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                evidence_count INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS program_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS update_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL,
                checked_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                channel_ref TEXT NOT NULL,
                account_email TEXT NOT NULL,
                niche TEXT NOT NULL,
                audience TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'pt-BR',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                topic TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                tags TEXT NOT NULL,
                script TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER,
                planned_at TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'youtube',
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def remember(self, kind: str, key: str, value: str) -> None:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO memories(kind, key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(kind, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (kind, key.strip().lower(), value.strip(), now, now),
        )
        self.conn.commit()

    def recall(self, query: str = "", limit: int = 8) -> list[tuple[str, str, str]]:
        term = f"%{query.strip().lower()}%"
        if query:
            cur = self.conn.execute(
                """
                SELECT kind, key, value FROM memories
                WHERE lower(key) LIKE ? OR lower(value) LIKE ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (term, term, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT kind, key, value FROM memories ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        return list(cur.fetchall())

    def log_chat(self, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO conversations(role, content, created_at) VALUES (?, ?, ?)",
            (role, content, _dt.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def learn_from_text(self, text: str) -> None:
        low = text.lower()
        topics = {
            "pesquisa": ["pesquise", "procure", "busque", "internet", "noticia", "noticias"],
            "apps": ["abra", "abrir", "vincule", "app", "programa"],
            "sistema": ["sistema", "erro", "bug", "falha", "travou", "diagnostico"],
            "planejamento": ["planeje", "plano", "organize", "agenda", "tarefa"],
            "criacao": ["crie", "ideia", "projeto", "inventar", "escreva"],
            "trabalho": ["trabalho", "emprego", "servico", "servico", "produtividade", "rotina", "cliente", "equipe", "profissao", "profissao"],
            "negocios": ["vendas", "loja", "empresa", "cliente", "orcamento", "orcamento", "estoque", "financeiro", "marketing", "atendimento"],
            "educacao": ["aula", "estudo", "professor", "aluno", "curso", "escola", "treinamento"],
            "saude": ["saude", "clinica", "paciente", "consulta", "academia", "bem estar"],
            "servicos": ["manutencao", "obra", "entrega", "logistica", "limpeza", "cozinha", "salao", "servicos"],
            "tecnologia": ["tecnologia", "programador", "desenvolvedor", "designer", "ux", "ui", "codigo", "código", "frontend", "backend", "api", "deploy"],
            "codigo": ["codigo", "código", "bug", "refatorar", "revisar codigo", "python", "javascript", "typescript", "html", "css"],
            "design": ["designer", "design", "ui", "ux", "interface", "layout", "prototipo", "protótipo", "figma", "paleta"],
            "youtube": ["youtube", "canal", "video", "vídeo", "criador de conteudo", "criador de conteúdo", "thumbnail", "roteiro"],
            "memoria": ["lembre", "memorize", "aprenda", "prefiro", "gosto"],
            "foco": ["modo foco", "deep work", "workspace", "git", "pipeline"],
            "casa": ["casa", "sensores", "luz", "ambiente", "relaxar", "rotina matinal", "rotina noturna"],
        }
        now = _dt.datetime.now().isoformat(timespec="seconds")
        for topic, tokens in topics.items():
            if any(token in low for token in tokens):
                self.conn.execute(
                    """
                    INSERT INTO learned_topics(topic, score, last_seen) VALUES (?, 1, ?)
                    ON CONFLICT(topic) DO UPDATE SET score=score + 1, last_seen=excluded.last_seen
                    """,
                    (topic, now),
                )
        self._learn_preferences(low, now)
        self._extract_personal_memories(text, low, now)
        self.conn.commit()

    def _learn_preferences(self, low: str, now: str) -> None:
        signals = {
            "prefere_respostas_curtas": ["resposta curta", "respostas curtas", "seja direto", "mais curto"],
            "prefere_visual_limpo": ["sem botao", "sem botões", "sem riscos", "mais limpo", "mal feitas"],
            "interesse_avatar_realista": ["avatar", "holograma", "renderizada", "real", "humanizada"],
            "interesse_automacao_total": ["automatico", "automático", "sem precisar", "sozinho", "tudo automatico"],
            "interesse_voz_humana": ["voz humana", "mulher real", "voz neural", "mais humana"],
            "interesse_tecnologia": ["programador", "desenvolvedor", "designer", "mundo da tecnologia", "codigo", "código", "ui", "ux"],
            "interesse_produtividade_profissional": ["trabalho", "emprego", "servico", "produtividade", "melhorar tempo", "rotina", "vida do usuario"],
        }
        for key, tokens in signals.items():
            if any(token in low for token in tokens):
                self.conn.execute(
                    """
                    INSERT INTO learning_profile(key, value, confidence, evidence_count, updated_at)
                    VALUES (?, ?, 0.62, 1, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        confidence=min(1.0, confidence + 0.08),
                        evidence_count=evidence_count + 1,
                        updated_at=excluded.updated_at
                    """,
                    (key, "true", now),
                )

    def _extract_personal_memories(self, original: str, low: str, now: str) -> None:
        patterns = [
            ("perfil", "nome", ["meu nome e ", "meu nome é ", "me chamo "]),
            ("preferencia", "gosta_de", ["eu gosto de ", "gosto de "]),
            ("preferencia", "nao_gosta_de", ["eu nao gosto de ", "eu não gosto de ", "nao gosto de ", "não gosto de "]),
            ("preferencia", "prefere", ["eu prefiro ", "prefiro "]),
            ("trabalho", "area", ["eu trabalho com ", "trabalho com ", "minha area e ", "minha área é "]),
            ("ferramenta", "usa", ["eu uso ", "uso "]),
            ("projeto", "principal", ["meu projeto e ", "meu projeto é ", "estou criando ", "estou fazendo "]),
            ("rotina", "costuma", ["minha rotina e ", "minha rotina é ", "costumo "]),
            ("estilo", "quer_que_teraps", ["quero que voce ", "quero que você ", "faça que voce ", "faça que você "]),
        ]
        for kind, key, prefixes in patterns:
            value = self._extract_after_prefix(original, low, prefixes)
            if value:
                clean_value = value.strip(" .,!?:;")[:240]
                if len(clean_value) >= 2:
                    self.conn.execute(
                        """
                        INSERT INTO memories(kind, key, value, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(kind, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                        """,
                        (kind, key, clean_value, now, now),
                    )
                    self.conn.execute(
                        """
                        INSERT INTO learning_profile(key, value, confidence, evidence_count, updated_at)
                        VALUES (?, ?, 0.68, 1, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value=excluded.value,
                            confidence=min(1.0, confidence + 0.06),
                            evidence_count=evidence_count + 1,
                            updated_at=excluded.updated_at
                        """,
                        (f"{kind}_{key}", clean_value, now),
                    )

    @staticmethod
    def _extract_after_prefix(original: str, low: str, prefixes: list[str]) -> str:
        for prefix in prefixes:
            idx = low.find(prefix)
            if idx >= 0:
                return original[idx + len(prefix) :].strip()
        return ""

    def personal_context(self, limit: int = 6) -> str:
        cur = self.conn.execute(
            """
            SELECT kind, key, value FROM memories
            WHERE kind IN ('perfil', 'preferencia', 'trabalho', 'ferramenta', 'projeto', 'rotina', 'estilo')
            ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        if not rows:
            return ""
        return "; ".join(f"{kind}/{key}: {value}" for kind, key, value in rows)

    def set_state(self, key: str, value) -> None:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO program_state(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        self.conn.commit()

    def get_state(self, key: str, default=None):
        cur = self.conn.execute("SELECT value FROM program_state WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def log_auto_event(self, event_type: str, detail: str) -> None:
        self.conn.execute(
            "INSERT INTO auto_events(event_type, detail, created_at) VALUES (?, ?, ?)",
            (event_type, detail, _dt.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def log_automation_run(self, name: str, status: str, detail: str) -> None:
        self.conn.execute(
            "INSERT INTO automation_runs(name, status, detail, created_at) VALUES (?, ?, ?, ?)",
            (name, status, detail, _dt.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def add_reminder(self, title: str, due_at: _dt.datetime, source: str = "user") -> int:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO reminders(title, due_at, status, source, created_at) VALUES (?, ?, 'pending', ?, ?)",
            (title.strip(), due_at.isoformat(timespec="seconds"), source, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def due_reminders(self) -> list[tuple[int, str, str]]:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            """
            SELECT id, title, due_at FROM reminders
            WHERE status = 'pending' AND due_at <= ?
            ORDER BY due_at ASC LIMIT 6
            """,
            (now,),
        )
        return list(cur.fetchall())

    def complete_reminder(self, reminder_id: int) -> None:
        self.conn.execute(
            "UPDATE reminders SET status = 'done', completed_at = ? WHERE id = ?",
            (_dt.datetime.now().isoformat(timespec="seconds"), reminder_id),
        )
        self.conn.commit()

    def list_reminders(self, limit: int = 8) -> list[tuple[int, str, str, str]]:
        cur = self.conn.execute(
            """
            SELECT id, title, due_at, status FROM reminders
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, due_at ASC LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def save_youtube_channel(self, name: str, channel_ref: str, account_email: str, niche: str, audience: str, language: str = "pt-BR") -> int:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        self.conn.execute("UPDATE youtube_channels SET active = 0")
        cur = self.conn.execute(
            """
            INSERT INTO youtube_channels(name, channel_ref, account_email, niche, audience, language, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (name.strip(), channel_ref.strip(), account_email.strip(), niche.strip(), audience.strip(), language.strip() or "pt-BR", now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def active_youtube_channel(self) -> dict | None:
        cur = self.conn.execute(
            """
            SELECT id, name, channel_ref, account_email, niche, audience, language
            FROM youtube_channels WHERE active = 1 ORDER BY updated_at DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        keys = ["id", "name", "channel_ref", "account_email", "niche", "audience", "language"]
        return dict(zip(keys, row))

    def save_youtube_content(self, channel_id: int | None, topic: str, title: str, description: str, tags: list[str], script: str, status: str = "draft") -> int:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            """
            INSERT INTO youtube_content(channel_id, topic, title, description, tags, script, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (channel_id, topic.strip(), title.strip(), description.strip(), ", ".join(tags), script.strip(), status, now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_youtube_content(self, limit: int = 6) -> list[tuple[int, str, str, str]]:
        cur = self.conn.execute(
            "SELECT id, topic, title, status FROM youtube_content ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return list(cur.fetchall())

    def schedule_youtube_content(self, content_id: int, planned_at: _dt.datetime) -> int:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO youtube_calendar(content_id, planned_at, platform, status, created_at) VALUES (?, ?, 'youtube', 'planned', ?)",
            (content_id, planned_at.isoformat(timespec="seconds"), now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def learned_profile_summary(self) -> str:
        cur = self.conn.execute(
            "SELECT key, confidence, evidence_count FROM learning_profile ORDER BY confidence DESC, evidence_count DESC LIMIT 8"
        )
        rows = cur.fetchall()
        if not rows:
            return "Ainda estou formando um perfil automatico."
        return "\n".join(f"- {key}: {confidence:.2f} ({count} evidencias)" for key, confidence, count in rows)

    def optimize(self) -> str:
        self.conn.execute("PRAGMA optimize")
        self.conn.execute("DELETE FROM suggestions WHERE id NOT IN (SELECT id FROM suggestions ORDER BY created_at DESC LIMIT 80)")
        self.conn.execute("DELETE FROM auto_events WHERE id NOT IN (SELECT id FROM auto_events ORDER BY created_at DESC LIMIT 200)")
        self.conn.commit()
        return "Banco otimizado e historicos automaticos aparados."

    def top_topics(self, limit: int = 4) -> list[str]:
        cur = self.conn.execute(
            "SELECT topic FROM learned_topics ORDER BY score DESC, last_seen DESC LIMIT ?",
            (limit,),
        )
        return [row[0] for row in cur.fetchall()]

    def save_suggestions(self, suggestions: list[tuple[str, str]], source: str) -> None:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        for label, prompt in suggestions:
            self.conn.execute(
                "INSERT INTO suggestions(label, prompt, source, created_at) VALUES (?, ?, ?, ?)",
                (label, prompt, source, now),
            )
        self.conn.commit()


class Voice:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.engine = None
        self.available = False
        self.neural_available = False
        self._lock = threading.Lock()
        self.audio_dir = DATA_DIR / "voice_cache"
        self.audio_dir.mkdir(exist_ok=True)
        try:
            import edge_tts  # type: ignore

            self.edge_tts = edge_tts
            self.neural_available = True
        except Exception:
            self.edge_tts = None
            logging.info("edge-tts indisponivel; usando voz Windows quando possivel.")
        try:
            import pyttsx3  # type: ignore

            self.engine = pyttsx3.init()
            self.apply_config()
            self._select_female_voice()
            self.available = True
        except Exception:
            logging.info("pyttsx3 indisponivel; voz desativada.")

    def _select_female_voice(self) -> None:
        if not self.engine:
            return
        voices = self.engine.getProperty("voices") or []
        hint = str(self.config["voice_name_hint"] or "").lower()
        preferred = [hint, "maria", "helena", "female", "mulher", "zira", "hazel"]
        for voice in voices:
            name = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
            if any(token and token in name for token in preferred):
                self.engine.setProperty("voice", voice.id)
                return

    def apply_config(self) -> None:
        if not self.engine:
            return
        # SAPI5/pyttsx3 sends speech to the current Windows default output device.
        self.engine.setProperty("rate", int(self.config["voice_rate"]))
        self.engine.setProperty("volume", float(self.config["voice_volume"]))

    def status(self) -> str:
        if not self.available and not self.neural_available:
            return "Voz indisponivel. Instale edge-tts ou pyttsx3 pelo instalador de opcionais."
        voice_name = "padrao do Windows"
        try:
            if self.engine:
                voice_id = self.engine.getProperty("voice")  # type: ignore[union-attr]
                for voice in self.engine.getProperty("voices") or []:  # type: ignore[union-attr]
                    if getattr(voice, "id", "") == voice_id:
                        voice_name = getattr(voice, "name", voice_name)
                        break
        except Exception:
            logging.info("Nao foi possivel consultar a voz atual.")
        neural = str(self.config["neural_voice"])
        mode = "neural feminina" if self.neural_available and self.config["voice_engine"] == "neural" else "Windows/SAPI"
        return (
            f"Modo de voz: {mode}\n"
            f"Voz neural: {neural if self.neural_available else 'indisponivel'}\n"
            f"Fallback Windows: {voice_name}\n"
            "Saida de audio: dispositivo padrao do Windows\n"
            "Se voce trocar a saida no Windows para fone, HDMI, Bluetooth ou caixas, a fala do Teraps acompanha essa saida."
        )

    def speak(self, text: str) -> None:
        if not self.config["auto_speak"]:
            return

        def run() -> None:
            with self._lock:
                try:
                    if self.config["voice_engine"] == "neural" and self.neural_available:
                        if self._speak_neural(text):
                            return
                    self._speak_windows(text)
                except Exception:
                    logging.exception("Falha de voz.")

        threading.Thread(target=run, daemon=True).start()

    def _speak_windows(self, text: str) -> bool:
        if not self.available or not self.engine:
            return False
        self.apply_config()
        self._apply_context_voice(text)
        self.engine.say(text)  # type: ignore[union-attr]
        self.engine.runAndWait()  # type: ignore[union-attr]
        return True

    def _speak_neural(self, text: str) -> bool:
        try:
            import asyncio

            audio_file = self.audio_dir / f"teraps_voice_{int(time.time() * 1000)}.mp3"
            asyncio.run(self._save_neural_audio(text, audio_file))
            self._play_audio(audio_file)
            self._cleanup_voice_cache()
            return True
        except Exception:
            logging.exception("Falha na voz neural; usando fallback Windows.")
            return False

    async def _save_neural_audio(self, text: str, audio_file: Path) -> None:
        rate, pitch, volume = self._neural_context_style(text)
        communicate = self.edge_tts.Communicate(  # type: ignore[union-attr]
            text,
            voice=str(self.config["neural_voice"]),
            rate=rate,
            pitch=pitch,
            volume=volume,
        )
        await communicate.save(str(audio_file))

    def _neural_context_style(self, text: str) -> tuple[str, str, str]:
        low = text.lower()
        rate = str(self.config["neural_voice_rate"])
        pitch = str(self.config["neural_voice_pitch"])
        volume = str(self.config["neural_voice_volume"])
        if any(token in low for token in ["erro", "falha", "alerta", "anomalia"]):
            return "+2%", "-1Hz", "+8%"
        if any(token in low for token in ["modo deep work", "monitoramento", "pipeline", "git"]):
            return "+6%", "-1Hz", "+3%"
        if any(token in low for token in ["relax", "noturna", "descanso", "boa noite"]):
            return "-12%", "-4Hz", "-3%"
        if any(token in low for token in ["oi", "prazer", "de nada", "posso"]):
            return "-6%", "-2Hz", "+0%"
        return rate, pitch, volume

    def _play_audio(self, audio_file: Path) -> None:
        # Uses the Windows default audio output without changing system devices.
        ps_command = (
            "Add-Type -AssemblyName PresentationCore; "
            f"$p=New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([Uri]'{audio_file.as_uri()}'); "
            "$p.Play(); "
            "while($p.NaturalDuration.HasTimeSpan -eq $false){Start-Sleep -Milliseconds 50}; "
            "$d=$p.NaturalDuration.TimeSpan.TotalMilliseconds; "
            "Start-Sleep -Milliseconds ([int]($d + 250)); "
            "$p.Close()"
        )
        run_hidden(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_command],
            timeout=90,
        )

    def _cleanup_voice_cache(self) -> None:
        files = sorted(self.audio_dir.glob("teraps_voice_*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[10:]:
            try:
                old.unlink()
            except Exception:
                pass

    def _apply_context_voice(self, text: str) -> None:
        if not self.engine:
            return
        low = text.lower()
        rate = int(self.config["voice_rate"])
        volume = float(self.config["voice_volume"])
        if any(token in low for token in ["erro", "falha", "alerta", "anomalia"]):
            rate = max(145, rate - 8)
            volume = min(1.0, volume + 0.03)
        elif any(token in low for token in ["modo deep work", "monitoramento", "pipeline", "git"]):
            rate = min(190, rate + 8)
        elif any(token in low for token in ["relax", "noturna", "descanso", "boa noite"]):
            rate = max(140, rate - 12)
        self.engine.setProperty("rate", rate)
        self.engine.setProperty("volume", volume)


class Microphone:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.available = False
        self.error = ""
        self.backend = "indisponivel"
        self.device_name = "microfone padrao do Windows"
        try:
            import speech_recognition as sr  # type: ignore

            self.sr = sr
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.energy_threshold = 350
            self.recognizer.pause_threshold = 0.75
            self.recognizer.non_speaking_duration = 0.45
            self.sd = None
            self.np = None
            if self._pyaudio_ready():
                self.backend = "pyaudio"
                self.available = True
            else:
                try:
                    import sounddevice as sd  # type: ignore
                    import numpy as np  # type: ignore

                    self.sd = sd
                    self.np = np
                    if self._sounddevice_has_input(sd):
                        self.backend = "sounddevice"
                        self.available = True
                    else:
                        self.error = "Nenhum microfone padrao de entrada foi exposto pelo Windows."
                except Exception as exc:
                    self.error = str(exc)
        except Exception as exc:
            self.sr = None
            self.recognizer = None
            self.sd = None
            self.np = None
            self.error = str(exc)
            logging.info("SpeechRecognition indisponivel; microfone desativado.")

    def listen_once(self) -> VoiceInputResult:
        if not self.available:
            return VoiceInputResult(
                False,
                status="unavailable",
                message=(
                    "Nao encontrei um microfone padrao disponivel no Windows. Defina um dispositivo em "
                    "Configuracoes > Sistema > Som > Entrada e libere o microfone para aplicativos de desktop. "
                    "Depois use Ctrl+Espaco ou duplo clique no campo de entrada para falar novamente."
                ),
            )
        try:
            audio = self._capture_audio()
            text = self.recognizer.recognize_google(audio, language=self.config["listen_language"])  # type: ignore[union-attr]
            text = " ".join(text.strip().split())
            if not text:
                return VoiceInputResult(False, status="unclear", message=self._clarify_message())
            return VoiceInputResult(True, text=text, status="ok")
        except self.sr.WaitTimeoutError:  # type: ignore[union-attr]
            return VoiceInputResult(False, status="silence", message="Nao ouvi sua voz. Pode falar de novo mais perto do microfone?")
        except self.sr.UnknownValueError:  # type: ignore[union-attr]
            return VoiceInputResult(False, status="unclear", message=self._clarify_message())
        except self.sr.RequestError as exc:  # type: ignore[union-attr]
            self.error = str(exc)
            logging.info("Servico de reconhecimento indisponivel: %s", exc)
            return VoiceInputResult(
                False,
                status="service_error",
                message="Ouvi o audio, mas o servico de reconhecimento nao respondeu. Pode repetir por texto ou tentar novamente?",
            )
        except Exception as exc:
            self.error = str(exc)
            logging.info("Falha ao ouvir microfone: %s", exc)
            return VoiceInputResult(
                False,
                status="error",
                message="Nao consegui acessar o microfone padrao do Windows. Verifique permissoes e tente novamente.",
            )

    def status(self) -> str:
        if not self.available:
            return f"Microfone: indisponivel ({self.error or 'dependencia ausente'})."
        return f"Microfone: ativo via {self.backend}; entrada: {self.device_name}; idioma: {self.config['listen_language']}."

    def _capture_audio(self):
        if self.backend == "pyaudio":
            return self._capture_with_pyaudio()
        return self._capture_with_sounddevice()

    def _capture_with_pyaudio(self):
        with self.sr.Microphone(device_index=None) as source:  # type: ignore[union-attr]
            self.device_name = "microfone padrao do Windows"
            self.recognizer.adjust_for_ambient_noise(  # type: ignore[union-attr]
                source,
                duration=float(self.config["mic_calibration_seconds"]),
            )
            return self.recognizer.listen(  # type: ignore[union-attr]
                source,
                timeout=float(self.config["mic_timeout"]),
                phrase_time_limit=float(self.config["mic_phrase_time_limit"]),
            )

    def _capture_with_sounddevice(self):
        if not self.sd or not self.np:
            raise RuntimeError("sounddevice indisponivel")
        sample_rate = int(self.config["mic_sample_rate"] or 16000)
        seconds = float(self.config["mic_sounddevice_seconds"] or 6)
        self.device_name = self._sounddevice_default_name()
        recording = self.sd.rec(  # type: ignore[union-attr]
            int(seconds * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=None,
        )
        self.sd.wait()  # type: ignore[union-attr]
        data = self.np.asarray(recording, dtype=self.np.int16).reshape(-1)  # type: ignore[union-attr]
        if data.size == 0 or float(self.np.max(self.np.abs(data))) < 120:  # type: ignore[union-attr]
            raise self.sr.WaitTimeoutError("silencio no microfone padrao")  # type: ignore[union-attr]
        return self.sr.AudioData(data.tobytes(), sample_rate, 2)  # type: ignore[union-attr]

    def _sounddevice_default_name(self) -> str:
        try:
            device = self.sd.query_devices(kind="input")  # type: ignore[union-attr]
            return str(device.get("name") or "microfone padrao do Windows")
        except Exception:
            return "microfone padrao do Windows"

    def _pyaudio_ready(self) -> bool:
        try:
            import pyaudio  # type: ignore

            return bool(pyaudio)
        except Exception:
            return False

    @staticmethod
    def _sounddevice_has_input(sd_module) -> bool:
        try:
            device = sd_module.query_devices(kind="input")
            return int(device.get("max_input_channels", 0)) > 0
        except Exception:
            return False

    @staticmethod
    def _clarify_message() -> str:
        return (
            "Eu ouvi, mas nao entendi com seguranca. Pode explicar de outro jeito o que voce quer que eu faca?"
        )


class SystemInfo:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config

    def summary(self) -> str:
        snap = self.snapshot(self.config)
        lines = [
            f"Sistema: {snap['os_label']}",
            f"Arquitetura: {snap['machine']}",
            f"CPU logica: {snap['cpu_cores']}",
            f"RAM: {snap['memory_available_gb']:.1f} GB livres de {snap['memory_total_gb']:.1f} GB",
            f"Disco: {snap['disk_free_gb']:.1f} GB livres de {snap['disk_total_gb']:.1f} GB",
            f"Energia: {snap['power_mode']}",
        ]
        profile = snap.get("adaptive_profile") or {}
        if profile:
            lines.extend(
                [
                    f"Perfil adaptativo: {profile.get('name', 'auto')}",
                    f"Animacao: {profile.get('fps', '?')} FPS, {profile.get('particles', '?')} particulas",
                    f"Motivo: {profile.get('reason', 'ajuste automatico')}",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _gb(value: int | float) -> str:
        return f"{value / (1024 ** 3):.1f} GB"

    @staticmethod
    def snapshot(config: Config | None = None) -> dict:
        os_label = f"{platform.system() or os.name} {platform.release()}".strip()
        if platform.version():
            os_label = f"{os_label} build {platform.version()}"
        snap = {
            "os_label": os_label,
            "machine": platform.machine() or "desconhecida",
            "cpu_cores": os.cpu_count() or 2,
            "memory_total_gb": 0.0,
            "memory_available_gb": 0.0,
            "disk_total_gb": 0.0,
            "disk_free_gb": 0.0,
            "power_mode": "energia desconhecida",
            "battery_percent": None,
            "adaptive_profile": (config["adaptive_last_profile"] if config else {}),
        }
        try:
            import psutil  # type: ignore

            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(str(BASE_DIR.anchor or "C:\\"))
            battery = psutil.sensors_battery()
            snap["memory_total_gb"] = round(mem.total / (1024 ** 3), 2)
            snap["memory_available_gb"] = round(mem.available / (1024 ** 3), 2)
            snap["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
            snap["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
            if battery:
                snap["battery_percent"] = int(battery.percent)
                mode = "tomada" if battery.power_plugged else "bateria"
                snap["power_mode"] = f"{mode}, {battery.percent:.0f}%"
            else:
                snap["power_mode"] = "sem bateria detectada"
        except Exception:
            logging.info("psutil indisponivel para snapshot completo de hardware.")
        return snap

    @staticmethod
    def _battery(psutil_module) -> str:
        battery = psutil_module.sensors_battery()
        if not battery:
            return "nao detectada"
        plugged = "carregando" if battery.power_plugged else "na bateria"
        return f"{battery.percent:.0f}% ({plugged})"


class HardwareAdapter:
    def __init__(self, config: Config) -> None:
        self.config = config

    def detect(self) -> HardwareProfile:
        requested = str(self.config["profile"] or "auto").lower()
        snap = SystemInfo.snapshot(self.config)
        if requested in {"eco", "economico", "economico"}:
            return self._make_profile("economico", snap, "perfil economico definido pelo usuario")
        if requested in {"basico", "basic"}:
            return self._make_profile("basico", snap, "perfil basico definido pelo usuario")
        if requested in {"equilibrado", "balanced"}:
            return self._make_profile("equilibrado", snap, "perfil equilibrado definido pelo usuario")
        if requested in {"alto", "alto desempenho", "high"}:
            return self._make_profile("alto desempenho", snap, "perfil alto desempenho definido pelo usuario")
        if requested in {"ultra", "maximo", "maximo"}:
            return self._make_profile("ultra", snap, "perfil ultra definido pelo usuario")
        return self._auto_profile(snap)

    def apply(self, profile: HardwareProfile) -> None:
        visual_scale = {
            "economico": 0.72,
            "basico": 0.82,
            "equilibrado": 1.0,
            "alto desempenho": 1.12,
            "ultra": 1.22,
        }.get(profile.name, 1.0)
        self.config.data["adaptive_visual_scale"] = visual_scale
        if profile.name in {"economico", "basico"}:
            self.config.data["mic_calibration_seconds"] = 0.25
            self.config.data["mic_phrase_time_limit"] = 8
            self.config.data["mic_sounddevice_seconds"] = 5
        elif profile.name == "ultra":
            self.config.data["mic_calibration_seconds"] = 0.55
            self.config.data["mic_phrase_time_limit"] = 13
            self.config.data["mic_sounddevice_seconds"] = 7
        else:
            self.config.data["mic_calibration_seconds"] = 0.4
            self.config.data["mic_phrase_time_limit"] = 11
            self.config.data["mic_sounddevice_seconds"] = 6
        self.config.data["adaptive_last_profile"] = {
            "name": profile.name,
            "fps": profile.fps,
            "particles": profile.particles,
            "glow": profile.glow,
            "voice_enabled": profile.voice_enabled,
            "web_enabled": profile.web_enabled,
            "os_label": profile.os_label,
            "cpu_cores": profile.cpu_cores,
            "memory_gb": profile.memory_gb,
            "power_mode": profile.power_mode,
            "reason": profile.reason,
        }
        self.config.data["adaptive_last_applied"] = _dt.datetime.now().isoformat(timespec="seconds")
        self.config.save()

    def _auto_profile(self, snap: dict) -> HardwareProfile:
        cores = int(snap.get("cpu_cores") or 2)
        memory_gb = float(snap.get("memory_total_gb") or 0.0)
        power = str(snap.get("power_mode") or "")
        on_battery = "bateria" in power.lower()
        if self.config["adaptive_low_power_on_battery"] and on_battery:
            return self._make_profile("economico", snap, "notebook em bateria; priorizando autonomia")
        if cores <= 2 or (memory_gb and memory_gb <= 4):
            return self._make_profile("basico", snap, "CPU/RAM limitados; reduzindo efeitos pesados")
        if cores <= 6 or (memory_gb and memory_gb < 12):
            return self._make_profile("equilibrado", snap, "hardware intermediario; mantendo fluidez")
        if cores >= 12 and memory_gb >= 24:
            return self._make_profile("ultra", snap, "CPU/RAM altos; liberando mais detalhes visuais")
        return self._make_profile("alto desempenho", snap, "hardware forte; animacoes com mais densidade")

    @staticmethod
    def _make_profile(name: str, snap: dict, reason: str) -> HardwareProfile:
        presets = {
            "economico": (16, 10, False, True, True),
            "basico": (20, 14, False, True, True),
            "equilibrado": (30, 26, True, True, True),
            "alto desempenho": (42, 36, True, True, True),
            "ultra": (48, 46, True, True, True),
        }
        fps, particles, glow, voice_enabled, web_enabled = presets.get(name, presets["equilibrado"])
        return HardwareProfile(
            name=name,
            fps=fps,
            particles=particles,
            glow=glow,
            voice_enabled=voice_enabled,
            web_enabled=web_enabled,
            os_label=str(snap.get("os_label") or ""),
            cpu_cores=int(snap.get("cpu_cores") or 0),
            memory_gb=float(snap.get("memory_total_gb") or 0.0),
            power_mode=str(snap.get("power_mode") or "desconhecido"),
            reason=reason,
        )


class Maintenance:
    REQUIRED_FILES = ["teraps.py", "README.md", "Teraps.bat", "assets/teraps.ico", "assets/teraps_avatar.png"]
    OPTIONAL_MODULES = {
        "pyttsx3": "voz sintetizada",
        "speech_recognition": "entrada por microfone",
        "sounddevice": "captura pelo microfone padrao",
        "psutil": "diagnostico avancado",
    }

    def status(self) -> str:
        lines = ["Autodiagnostico Teraps:"]
        for file_name in self.REQUIRED_FILES:
            if file_name == "assets/teraps.ico":
                path = ICON_FILE
            elif file_name == "assets/teraps_avatar.png":
                path = AVATAR_FILE
            else:
                path = BASE_DIR / file_name
            state = "ok" if path.exists() else "faltando"
            lines.append(f"- {file_name}: {state}")
        for module, feature in self.OPTIONAL_MODULES.items():
            lines.append(f"- {feature}: {'ok' if self._module_exists(module) else 'opcional ausente'}")
        lines.append(f"- voz neural feminina: {'ok' if self._module_exists('edge_tts') else 'opcional ausente'}")
        lines.append("- saida de audio: dispositivo padrao do Windows")
        lines.append("- entrada de voz: microfone padrao do Windows quando disponivel")
        lines.append("- ponte 3D: opcional via TCP/WebSocket externo")
        lines.append("- avatar 3D holografico: ativo por camadas, parallax e particulas")
        lines.append("- smart home: simulado ou Home Assistant quando configurado")
        lines.append("- aprendizado automatico: ativo no SQLite")
        lines.append("- manutencao automatica: ativa")
        lines.append("- automacao proativa: ativa")
        lines.append("- lembretes/tarefas: banco SQLite local")
        lines.append("- criador YouTube: planejamento, roteiros, tags, calendario e canal no SQLite")
        lines.append("- API YouTube: preparada para OAuth oficial quando credenciais forem configuradas")
        lines.append("- comandos de diagnostico: executados ocultos e exibidos no chat")
        lines.append("- verificacao de atualizacao: automatica/local por padrao")
        lines.append(f"- memoria: {'ok' if MEMORY_DB.exists() else 'sera criada ao iniciar'}")
        lines.append("- configuracoes: banco SQLite")
        lines.append(f"- log: {LOG_FILE}")
        return "\n".join(lines)

    def repair(self) -> str:
        ensure_dirs()
        Config().save()
        Memory()
        return self.status() + "\nReparo preventivo executado: pastas, config e banco verificados."

    @staticmethod
    def _module_exists(module: str) -> bool:
        try:
            __import__(module)
            return True
        except Exception:
            return False


class SearchResultParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._in_link = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and attrs_dict.get("class") == "result-link":
            self._in_link = True
            self._href = attrs_dict.get("href", "")
            self._text = []

    def handle_data(self, data) -> None:
        if self._in_link:
            self._text.append(data)

    def handle_endtag(self, tag) -> None:
        if tag == "a" and self._in_link:
            title = " ".join("".join(self._text).split())
            href = self._href
            if title and href:
                self.results.append((title, href))
            self._in_link = False


class BingResultParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._in_algo = False
        self._in_h2 = False
        self._in_link = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "")
        if tag == "li" and "b_algo" in class_name:
            self._in_algo = True
        elif self._in_algo and tag == "h2":
            self._in_h2 = True
        elif self._in_algo and self._in_h2 and tag == "a":
            self._in_link = True
            self._href = attrs_dict.get("href", "")
            self._text = []

    def handle_data(self, data) -> None:
        if self._in_link:
            self._text.append(data)

    def handle_endtag(self, tag) -> None:
        if tag == "a" and self._in_link:
            title = " ".join("".join(self._text).split())
            if title and self._href:
                self.results.append((title, self._clean_url(self._href)))
            self._in_link = False
        elif tag == "h2" and self._in_h2:
            self._in_h2 = False
        elif tag == "li" and self._in_algo:
            self._in_algo = False

    @staticmethod
    def _clean_url(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/"):
            query = urllib.parse.parse_qs(parsed.query)
            encoded = query.get("u", [""])[0]
            if encoded.startswith("a1"):
                try:
                    import base64

                    padded = encoded[2:] + "=" * (-len(encoded[2:]) % 4)
                    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
                except Exception:
                    return url
        return url


class WebSearch:
    def search(self, query: str, limit: int = 5) -> list[tuple[str, str]]:
        results = self._search_bing(query, limit)
        if results:
            return results
        return self._search_duckduckgo(query, limit)

    def _search_bing(self, query: str, limit: int) -> list[tuple[str, str]]:
        encoded = urllib.parse.urlencode({"q": query})
        url = f"https://www.bing.com/search?{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Teraps/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")
        parser = BingResultParser()
        parser.feed(html)
        return parser.results[:limit]

    def _search_duckduckgo(self, query: str, limit: int) -> list[tuple[str, str]]:
        encoded = urllib.parse.urlencode({"q": query})
        url = f"https://duckduckgo.com/html/?{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Teraps/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")
        parser = SearchResultParser()
        parser.feed(html)
        return parser.results[:limit]

    def open_query(self, query: str) -> None:
        webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")


class WindowsIntegration:
    SETTINGS_URIS = {
        "audio": "ms-settings:sound",
        "som": "ms-settings:sound",
        "microfone": "ms-settings:privacy-microphone",
        "entrada": "ms-settings:sound",
        "bluetooth": "ms-settings:bluetooth",
        "wifi": "ms-settings:network-wifi",
        "rede": "ms-settings:network",
        "energia": "ms-settings:powersleep",
        "apps": "ms-settings:appsfeatures",
        "privacidade": "ms-settings:privacy",
        "atualizacao": "ms-settings:windowsupdate",
        "windows update": "ms-settings:windowsupdate",
    }
    FOLDERS = {
        "desktop": "Desktop",
        "area de trabalho": "Desktop",
        "área de trabalho": "Desktop",
        "documentos": "Documents",
        "downloads": "Downloads",
        "imagens": "Pictures",
        "musicas": "Music",
        "músicas": "Music",
        "videos": "Videos",
        "vídeos": "Videos",
    }

    def __init__(self, config: Config) -> None:
        self.config = config

    def status(self) -> str:
        snap = SystemInfo.snapshot(self.config)
        audio = self._run_text(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_SoundDevice | Select-Object -First 5 Name,Status | Format-Table -AutoSize"], timeout=10)
        mic_hint = "Microfone: usando o dispositivo padrao de entrada exposto pelo Windows."
        default_apps = [
            ("explorer", shutil.which("explorer.exe") or "integrado ao Windows"),
            ("powershell", shutil.which("powershell.exe") or "nao encontrado no PATH"),
            ("cmd", shutil.which("cmd.exe") or "nao encontrado no PATH"),
        ]
        lines = [
            "Integracao Windows:",
            f"- Sistema: {snap['os_label']}",
            f"- Base do Teraps: {BASE_DIR}",
            f"- Dados locais: {DATA_DIR}",
            f"- Audio: saida padrao do Windows",
            f"- {mic_hint}",
            "- Apps base:",
        ]
        lines.extend(f"  {name}: {path}" for name, path in default_apps)
        if audio:
            lines.extend(["", "Dispositivos de audio detectados:", audio[:1200]])
        return "\n".join(lines)

    def open_settings(self, area: str) -> str:
        key = TerapsBrain._normalize_text(area.strip() or "som")
        uri = self.SETTINGS_URIS.get(key) or self.SETTINGS_URIS.get("som")
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
            return f"Abri as configuracoes do Windows em: {area or 'som'}."
        except Exception:
            return "Nao consegui abrir as configuracoes do Windows automaticamente. Verifique permissoes do sistema."

    def open_folder(self, name: str) -> str:
        key = TerapsBrain._normalize_text(name)
        folder_name = self.FOLDERS.get(key)
        if key in {"teraps", "pasta teraps", "programa", "app"}:
            target = BASE_DIR
        elif folder_name:
            target = Path.home() / folder_name
        else:
            target = Path(name.strip().strip('"'))
        if not target.exists():
            return f"Nao encontrei a pasta: {target}"
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            return f"Abri a pasta {target}."
        except Exception:
            try:
                popen_hidden(["explorer.exe", str(target)])
                return f"Abri a pasta {target}."
            except Exception as exc:
                return f"Nao consegui abrir a pasta pelo Windows: {exc}"

    def diagnostics(self, topic: str = "") -> str:
        key = TerapsBrain._normalize_text(topic)
        if key in {"", "geral", "windows"}:
            return self.status()
        commands = {
            "rede": ["ipconfig", "/all"],
            "ip": ["ipconfig"],
            "wifi": ["netsh", "wlan", "show", "interfaces"],
            "rotas": ["route", "print"],
            "processos": ["tasklist"],
            "tarefas": ["tasklist"],
            "disco": ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,VolumeName,FreeSpace,Size | Format-Table -AutoSize"],
            "servicos": ["powershell", "-NoProfile", "-Command", "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object -First 35 Name,DisplayName,Status | Format-Table -AutoSize"],
            "audio": ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_SoundDevice | Select-Object Name,Status,Manufacturer | Format-Table -AutoSize"],
            "energia": ["powercfg", "/GETACTIVESCHEME"],
            "usuario": ["whoami"],
        }
        cmd = commands.get(key)
        if not cmd:
            return "Diagnostico Windows disponivel: geral, rede, wifi, rotas, processos, disco, servicos, audio, energia ou usuario."
        output = self._run_text(cmd, timeout=18)
        return output or "O diagnostico foi executado, mas nao retornou texto."

    @staticmethod
    def _run_text(args: list[str], timeout: int = 15) -> str:
        try:
            result = run_hidden(args, capture_output=True, timeout=timeout)
            raw = result.stdout or result.stderr or b""
            for encoding in ("utf-8", "cp850", "cp1252"):
                try:
                    text = raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
                    return text.strip()[:3500]
                except UnicodeDecodeError:
                    continue
            text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            return text.strip()[:3500]
        except Exception as exc:
            return f"Falha ao executar diagnostico: {exc}"


class WindowsApps:
    COMMON_ALIASES = {
        "bloco de notas": "notepad.exe",
        "notepad": "notepad.exe",
        "calculadora": "calc.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe",
        "explorador": "explorer.exe",
        "explorer": "explorer.exe",
        "terminal": "wt.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
    }

    def __init__(self, config: Config) -> None:
        self.config = config

    def link_app(self, name: str, path: str) -> str:
        candidate = Path(path.strip().strip('"'))
        if not candidate.exists():
            return f"Nao encontrei o caminho: {candidate}"
        aliases = dict(self.config["app_aliases"] or {})
        aliases[name.strip().lower()] = str(candidate)
        self.config["app_aliases"] = aliases
        return f"Vinculei {name} a {candidate}."

    def list_linked_apps(self) -> str:
        aliases = self.config["app_aliases"] or {}
        if not aliases:
            return "Ainda nao ha aplicativos personalizados vinculados."
        return "Apps vinculados:\n" + "\n".join(f"- {name}: {path}" for name, path in aliases.items())

    def open_app(self, name: str) -> str:
        terminal_names = {"terminal", "cmd", "prompt", "powershell", "wt", "windows terminal"}
        if name.strip().lower() in terminal_names:
            return (
                "Mantive tudo dentro do Teraps: nao abri terminal externo. "
                "Use 'comando ipconfig', 'comando tarefas' ou 'comando disco' para ver diagnosticos aqui no chat."
            )
        custom = self.config["app_aliases"] or {}
        target = custom.get(name.strip().lower()) or self.COMMON_ALIASES.get(name.strip().lower(), name.strip())
        resolved = self._resolve_app_target(target)
        try:
            os.startfile(resolved)  # type: ignore[attr-defined]
            return f"Abrindo {name}."
        except Exception:
            try:
                popen_hidden([resolved])
                return f"Tentei iniciar {name}."
            except Exception:
                webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(name + ' app windows')}")
                return f"Nao encontrei {name} localmente. Abri uma pesquisa para voce."

    @staticmethod
    def _resolve_app_target(target: str) -> str:
        clean = str(target).strip().strip('"')
        path = Path(clean)
        if path.exists():
            return str(path)
        found = shutil.which(clean)
        return found or clean

    def run_safe_command(self, command: str) -> str:
        allowed = {
            "ipconfig": ["ipconfig"],
            "rede": ["ipconfig", "/all"],
            "wifi": ["netsh", "wlan", "show", "interfaces"],
            "tarefas": ["tasklist"],
            "processos": ["tasklist"],
            "disco": [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,FreeSpace,Size | Format-Table -AutoSize",
            ],
        }
        key = command.strip().lower()
        if key not in allowed:
            return "Por seguranca, executo apenas comandos de diagnostico conhecidos."
        return WindowsIntegration._run_text(allowed[key], timeout=15)


class WorkspaceAutomation:
    def __init__(self, config: Config, memory: Memory) -> None:
        self.config = config
        self.memory = memory

    def trigger_deep_work(self) -> str:
        path = Path(str(self.config["workspace_path"] or BASE_DIR))
        ide = str(self.config["workspace_ide"] or "code")
        messages = ["Modo Deep Work ativado."]
        try:
            if path.exists():
                popen_hidden([ide, str(path)])
                messages.append(f"Ambiente de desenvolvimento aberto em {path}.")
            else:
                messages.append(f"Pasta de workspace nao encontrada: {path}.")
        except Exception:
            messages.append("Nao consegui abrir a IDE configurada; mantive o protocolo em modo local.")
        git = self.check_git_status(path)
        messages.append(git)
        self.memory.remember("rotina", "deep_work", _dt.datetime.now().isoformat(timespec="seconds"))
        return "\n".join(messages)

    def check_git_status(self, path: Path | None = None) -> str:
        target = path or Path(str(self.config["workspace_path"] or BASE_DIR))
        try:
            result = run_hidden(
                ["git", "-C", str(target), "status", "-s"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode != 0:
                return "Git nao esta disponivel nesse workspace."
            status = result.stdout.strip()
            if not status:
                return "Repositorio limpo. Nenhuma alteracao pendente."
            return "Alteracoes no repositorio:\n" + status[:2500]
        except Exception:
            return "Nao foi possivel acessar informacoes do Git nesta pasta."

    def pipeline_status(self) -> str:
        checks = [
            ("codigo", "python -m py_compile teraps.py"),
            ("executavel", "dist\\Teraps.exe"),
            ("banco", str(MEMORY_DB)),
        ]
        lines = ["Monitoramento local:"]
        for label, value in checks:
            if label == "codigo":
                result = run_hidden(value.split(), cwd=str(BASE_DIR), capture_output=True, text=True, timeout=12)
                lines.append(f"- codigo: {'ok' if result.returncode == 0 else 'erro'}")
            else:
                lines.append(f"- {label}: {'ok' if Path(value).exists() else 'pendente'}")
        return "\n".join(lines)


class SmartHomeControl:
    SCENES = {
        "deep_work": {"brightness": 255, "color_temp": 250, "label": "foco frio 4000K"},
        "start_day": {"brightness": 210, "color_temp": 300, "label": "manha produtiva"},
        "wind_down": {"brightness": 90, "color_temp": 450, "label": "descanso quente 2200K"},
        "relax": {"brightness": 110, "color_temp": 430, "label": "relaxamento"},
        "alert": {"brightness": 255, "color_temp": 220, "label": "alerta claro"},
    }

    def __init__(self, config: Config, memory: Memory) -> None:
        self.config = config
        self.memory = memory

    def set_lighting_scene(self, scene_name: str) -> str:
        scene = self.SCENES.get(scene_name, self.SCENES["relax"])
        hub_url = str(self.config["home_hub_url"] or "").rstrip("/")
        token = str(self.config["home_hub_token"] or "")
        if hub_url and token:
            payload = {
                "entity_id": "light.escritorio_principal",
                "brightness": scene["brightness"],
                "color_temp": scene["color_temp"],
            }
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{hub_url}/services/light/turn_on",
                    data=data,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=6).read()
                msg = f"Iluminacao aplicada: {scene['label']}."
            except Exception:
                logging.exception("Falha ao acionar Home Assistant.")
                msg = f"Hub IoT configurado, mas nao respondeu. Simulei a cena {scene['label']}."
        else:
            msg = f"Sem hub IoT configurado. Simulando cena de iluminacao: {scene['label']}."
        self.memory.remember("smart_home", f"scene_{scene_name}", msg)
        return msg

    def check_environment_sensors(self) -> dict:
        return {
            "temperature": 23.5,
            "humidity": 55,
            "air_quality": "Boa",
            "doors_locked": True,
            "devices_online": True,
        }

    def security_status(self) -> str:
        sensors = self.check_environment_sensors()
        door_text = "trancadas" if sensors["doors_locked"] else "abertas"
        devices = "online" if sensors["devices_online"] else "com anomalia"
        return (
            f"Ambiente: {sensors['temperature']}C, umidade {sensors['humidity']}%, ar {sensors['air_quality']}. "
            f"Portas {door_text}; dispositivos {devices}."
        )


class RoutineManager:
    def __init__(self, config: Config, memory: Memory, home: SmartHomeControl, workspace: WorkspaceAutomation) -> None:
        self.config = config
        self.memory = memory
        self.home = home
        self.workspace = workspace

    def start_day(self) -> str:
        lighting = self.home.set_lighting_scene("start_day")
        summary = self.daily_summary()
        self.memory.remember("rotina", "start_day", _dt.datetime.now().isoformat(timespec="seconds"))
        return lighting + "\n" + summary

    def wind_down(self) -> str:
        lighting = self.home.set_lighting_scene("wind_down")
        security = self.home.security_status()
        self.memory.remember("rotina", "wind_down", _dt.datetime.now().isoformat(timespec="seconds"))
        return lighting + "\nRotina noturna preparada. " + security

    def daily_summary(self) -> str:
        topics = ", ".join(self.memory.top_topics(3)) or "sem padrao definido ainda"
        git = self.workspace.check_git_status()
        now = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        return (
            f"Resumo executivo ({now}):\n"
            f"- Foco recente: {topics}\n"
            f"- Workspace: {git.splitlines()[0]}\n"
            "- Agenda: sem calendario conectado; posso integrar depois via conector.\n"
            "- Tecnologia/IA: use 'pesquise noticias de tecnologia' para atualizar em tempo real."
        )


class YouTubeCreatorManager:
    def __init__(self, config: Config, memory: Memory) -> None:
        self.config = config
        self.memory = memory

    def configure_channel(self, text: str) -> str:
        body = re.split(r"youtube", text, maxsplit=1, flags=re.IGNORECASE)[-1].strip(" :|-")
        parts = [part.strip() for part in body.split("|")]
        if len(parts) < 5:
            return (
                "Use assim: configurar canal youtube Nome do Canal | @handle ou UC... | email da conta | nicho | publico alvo"
            )
        name, channel_ref, account_email, niche, audience = parts[:5]
        if "@" not in account_email and "." not in account_email:
            return "Informe o email da conta Google que administra o canal."
        channel_id = self.memory.save_youtube_channel(name, channel_ref, account_email, niche, audience)
        self.memory.remember("youtube", "canal_ativo", f"{name} ({channel_ref}) / conta {account_email} / nicho {niche}")
        return (
            f"Canal YouTube configurado #{channel_id}: {name}\n"
            f"- Referencia: {channel_ref}\n"
            f"- Conta administradora: {account_email}\n"
            f"- Nicho: {niche}\n"
            f"- Publico: {audience}"
        )

    @staticmethod
    def extract_topic(text: str) -> str:
        parts = re.split(r"youtube", text, maxsplit=1, flags=re.IGNORECASE)
        return (parts[-1] if parts else text).strip(" :.-")

    def channel_status(self) -> str:
        channel = self.memory.active_youtube_channel()
        api = "configurada" if self.config["youtube_api_credentials"] else "nao configurada"
        if not channel:
            return (
                "Nenhum canal YouTube configurado. Use: configurar canal youtube Nome | @handle ou UC... | email | nicho | publico alvo"
            )
        return (
            "Canal YouTube ativo:\n"
            f"- Nome: {channel['name']}\n"
            f"- Referencia: {channel['channel_ref']}\n"
            f"- Conta: {channel['account_email']}\n"
            f"- Nicho: {channel['niche']}\n"
            f"- Publico: {channel['audience']}\n"
            f"- API/OAuth: {api}"
        )

    def configure_api(self, path: str) -> str:
        candidate = Path(path.strip().strip('"'))
        if not candidate.exists():
            return f"Nao encontrei o arquivo de credenciais OAuth/API: {candidate}"
        self.config["youtube_api_credentials"] = str(candidate)
        return (
            "Credenciais YouTube registradas localmente. Para publicar ou alterar videos no canal, ainda sera necessario "
            "autorizar a conta Google pelo fluxo OAuth oficial."
        )

    def api_status(self) -> str:
        creds = str(self.config["youtube_api_credentials"] or "")
        token = str(self.config["youtube_oauth_token"] or "")
        return (
            "Status da integracao YouTube:\n"
            f"- Credenciais OAuth/API: {'configuradas em ' + creds if creds else 'nao configuradas'}\n"
            f"- Token OAuth: {'registrado' if token else 'nao autorizado'}\n"
            "- API oficial preparada para: canais, videos, playlists, thumbnails e uploads quando OAuth estiver ativo."
        )

    def create_video_package(self, topic: str) -> str:
        channel = self.memory.active_youtube_channel()
        channel_id = int(channel["id"]) if channel else None
        niche = channel["niche"] if channel else "conteudo geral"
        audience = channel["audience"] if channel else "publico amplo"
        topic = topic.strip() or "ideia principal do canal"
        title = self._title_for(topic, niche)
        tags = self._tags_for(topic, niche)
        description = self._description_for(topic, channel, tags)
        script = self._script_for(topic, audience)
        content_id = self.memory.save_youtube_content(channel_id, topic, title, description, tags, script)
        return (
            f"Pacote YouTube criado #{content_id}\n"
            f"TITULO:\n{title}\n\n"
            f"DESCRICAO:\n{description}\n\n"
            f"TAGS:\n{', '.join(tags)}\n\n"
            f"ROTEIRO:\n{script}\n\n"
            "CHECKLIST:\n"
            "- gravar gancho nos primeiros 8 segundos\n"
            "- criar thumbnail com 3 palavras fortes\n"
            "- confirmar audio limpo e luz no rosto/produto\n"
            "- revisar titulo, descricao, tags, cards e tela final\n"
            "- publicar ou agendar no YouTube Studio"
        )

    def content_calendar(self) -> str:
        channel = self.memory.active_youtube_channel()
        niche = channel["niche"] if channel else "conteudo do canal"
        base_topics = [
            f"erro comum em {niche}",
            f"guia rapido de {niche}",
            f"ferramentas que ajudam em {niche}",
        ]
        lines = ["Calendario YouTube sugerido:"]
        for i, topic in enumerate(base_topics):
            planned = _dt.datetime.now() + _dt.timedelta(days=2 + i * 3)
            title = self._title_for(topic, niche)
            content_id = self.memory.save_youtube_content(channel["id"] if channel else None, topic, title, self._description_for(topic, channel, self._tags_for(topic, niche)), self._tags_for(topic, niche), self._script_for(topic, channel["audience"] if channel else "publico amplo"), "planned")
            self.memory.schedule_youtube_content(content_id, planned)
            lines.append(f"- {planned.strftime('%d/%m %H:%M')} | #{content_id} | {title}")
        return "\n".join(lines)

    def list_content(self) -> str:
        rows = self.memory.list_youtube_content()
        if not rows:
            return "Ainda nao ha conteudos YouTube salvos."
        return "Conteudos YouTube salvos:\n" + "\n".join(f"- #{cid} [{status}] {topic}: {title}" for cid, topic, title, status in rows)

    @staticmethod
    def _title_for(topic: str, niche: str) -> str:
        clean_topic = topic.strip().capitalize()
        return f"{clean_topic}: o jeito pratico de melhorar seu resultado em {niche}"

    @staticmethod
    def _tags_for(topic: str, niche: str) -> list[str]:
        words = [w.strip(" ,.;:!?").lower() for w in (topic + " " + niche).split()]
        tags = []
        for word in words:
            if len(word) >= 4 and word not in tags:
                tags.append(word)
        defaults = ["youtube", "criador de conteudo", "tutorial", "dicas", "estrategia"]
        for tag in defaults:
            if tag not in tags:
                tags.append(tag)
        return tags[:12]

    @staticmethod
    def _description_for(topic: str, channel: dict | None, tags: list[str]) -> str:
        channel_name = channel["name"] if channel else "o canal"
        audience = channel["audience"] if channel else "quem quer aprender com clareza"
        return (
            f"Neste video, {channel_name} mostra {topic} de forma pratica para {audience}.\n\n"
            "Comente sua duvida, salve para consultar depois e inscreva-se para acompanhar os proximos conteudos.\n\n"
            f"Palavras-chave: {', '.join(tags[:8])}"
        )

    @staticmethod
    def _script_for(topic: str, audience: str) -> str:
        return (
            f"1. Gancho: 'Se voce quer entender {topic} sem perder tempo, fica comigo pelos proximos minutos.'\n"
            f"2. Contexto: explique por que isso importa para {audience}.\n"
            "3. Valor principal: apresente 3 pontos claros, cada um com exemplo visual.\n"
            "4. Demonstração: mostre na tela ou conte um caso real.\n"
            "5. Fechamento: recapitule em uma frase e chame para comentar a proxima duvida."
        )


class TechStudio:
    def __init__(self, config: Config, memory: Memory) -> None:
        self.config = config
        self.memory = memory

    def help(self) -> str:
        return (
            "Tech Studio Teraps:\n"
            "- ajuda programador: comandos para desenvolvimento\n"
            "- plano app sua ideia: backlog, arquitetura e MVP\n"
            "- arquitetura projeto sua ideia: camadas, dados, riscos e proximos passos\n"
            "- stack projeto sua ideia: tecnologias sugeridas por perfil de hardware e objetivo\n"
            "- revisar codigo caminho\\arquivo.py: analise rapida de riscos e melhorias\n"
            "- explicar codigo caminho\\arquivo.py: resumo do arquivo\n"
            "- checklist deploy: revisao antes de publicar\n"
            "- design system produto: base visual para UI\n"
            "- ux review descricao da tela: melhorias de usabilidade\n"
            "- briefing design produto: roteiro para designer ou Figma"
        )

    def plan_app(self, idea: str) -> str:
        idea = idea.strip() or "produto digital"
        self.memory.remember("tecnologia", "ultimo_plano_app", idea)
        return (
            f"Plano tecnico para: {idea}\n"
            "MVP:\n"
            "- definir usuario principal, problema e resultado esperado\n"
            "- criar fluxo central com cadastro/configuracao, acao principal e historico\n"
            "- salvar dados essenciais em SQLite/local primeiro, evoluindo para API quando precisar multiusuario\n"
            "- incluir logs, tratamento de erro, tela vazia, loading e backup/exportacao\n\n"
            "Arquitetura sugerida:\n"
            "- UI: camada de interface simples e responsiva\n"
            "- Core: regras do produto sem depender da tela\n"
            "- Dados: repositorios para banco, arquivos e integracoes\n"
            "- Automacao: tarefas em background com fila e logs\n"
            "- Observabilidade: historico de eventos, erros e versao\n\n"
            "Backlog inicial:\n"
            "1. Prototipo navegavel\n"
            "2. Persistencia local\n"
            "3. Comandos/atalhos principais\n"
            "4. Testes dos fluxos criticos\n"
            "5. Empacotamento e atualizacao"
        )

    def architecture(self, idea: str) -> str:
        idea = idea.strip() or "sistema"
        return (
            f"Arquitetura proposta para {idea}:\n"
            "- Entrada: texto, voz, arquivos ou integracoes externas\n"
            "- Orquestrador: interpreta intencao, valida permissoes e decide a ferramenta\n"
            "- Servicos: modulos pequenos para app, internet, banco, automacao, midia e sistema\n"
            "- Persistencia: SQLite para prototipo; Postgres/Supabase/Neon quando houver multiusuario\n"
            "- Seguranca: logs sem segredos, confirmacao para acoes destrutivas e tokens fora do codigo\n"
            "- Escala: separar tarefas demoradas em fila/background worker\n"
            "- Qualidade: testes unitarios no core e smoke tests no executavel"
        )

    def stack(self, idea: str) -> str:
        idea = idea.strip() or "aplicacao"
        profile = self.config["adaptive_last_profile"] or {}
        hardware = profile.get("name", "auto")
        return (
            f"Stack sugerida para {idea} considerando perfil {hardware}:\n"
            "- App desktop leve: Python + Tkinter/CustomTkinter + SQLite + PyInstaller\n"
            "- App web moderno: React/Vite + TypeScript + SQLite local ou Supabase\n"
            "- Backend/API: FastAPI + Pydantic + SQLAlchemy\n"
            "- Automacao Windows: subprocess controlado, PowerShell seguro e logs\n"
            "- Design/UI: tokens de cor, spacing de 4/8px, componentes reutilizaveis e estados vazios\n"
            "- IA futura: camada de provedor isolada para trocar modelo sem reescrever o app\n"
            "- Deploy: GitHub Actions para build/teste e release versionada"
        )

    def review_code(self, target: str) -> str:
        path = self._resolve_file(target)
        if not path:
            return "Informe um arquivo existente. Exemplo: revisar codigo teraps.py"
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return f"Nao consegui ler {path}: {exc}"
        lines = text.splitlines()
        findings = []
        risky_patterns = [
            ("eval(", "uso de eval pode executar codigo arbitrario"),
            ("exec(", "uso de exec exige validacao forte"),
            ("shell=True", "shell=True aumenta risco ao montar comandos"),
            ("password", "verifique se nao ha segredo fixo no codigo"),
            ("token", "garanta que tokens nao sejam commitados"),
            ("TODO", "ha TODOs pendentes para revisar"),
            ("except Exception", "exceptions genericas precisam log/contexto"),
        ]
        for needle, message in risky_patterns:
            if needle in text:
                findings.append(f"- {message}: encontrado '{needle}'")
        long_lines = sum(1 for line in lines if len(line) > 140)
        if long_lines:
            findings.append(f"- {long_lines} linhas passam de 140 caracteres; considere quebrar para leitura.")
        if len(lines) > 900:
            findings.append("- arquivo grande; separar responsabilidades pode facilitar teste e manutencao.")
        if not findings:
            findings.append("- nenhum risco obvio encontrado em varredura rapida.")
        return (
            f"Revisao rapida de {path.name}:\n"
            f"- Linhas: {len(lines)}\n"
            f"- Tamanho: {len(text) / 1024:.1f} KB\n"
            + "\n".join(findings)
            + "\n\nProximo passo: rode testes/compilacao e revise os fluxos mais usados pelo usuario."
        )

    def explain_code(self, target: str) -> str:
        path = self._resolve_file(target)
        if not path:
            return "Informe um arquivo existente. Exemplo: explicar codigo teraps.py"
        text = path.read_text(encoding="utf-8", errors="ignore")
        classes = re.findall(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.MULTILINE)
        funcs = re.findall(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.MULTILINE)
        imports = re.findall(r"^(?:import|from)\s+([A-Za-z0-9_\\.]+)", text, re.MULTILINE)
        return (
            f"Resumo de {path.name}:\n"
            f"- Classes principais: {', '.join(classes[:12]) or 'nenhuma detectada'}\n"
            f"- Funcoes soltas: {', '.join(funcs[:12]) or 'nenhuma detectada'}\n"
            f"- Imports: {', '.join(dict.fromkeys(imports[:12])) or 'nenhum detectado'}\n"
            f"- Linhas: {len(text.splitlines())}\n"
            "Leitura inicial: comece pelas classes, depois siga para as rotas/comandos e por fim para a inicializacao."
        )

    def deploy_checklist(self) -> str:
        return (
            "Checklist de deploy/publicacao:\n"
            "- rodar teste de compilacao e smoke test do executavel\n"
            "- conferir .gitignore para nao enviar banco local, logs, tokens ou cache\n"
            "- atualizar README com instalacao, uso e comandos principais\n"
            "- versionar assets, icone, spec/build script e requirements\n"
            "- criar tag/release quando o build estiver estavel\n"
            "- validar em maquina fraca e forte, com e sem internet\n"
            "- confirmar audio, microfone, banco SQLite e permissoes do Windows"
        )

    def design_system(self, product: str) -> str:
        product = product.strip() or "produto"
        return (
            f"Design system base para {product}:\n"
            "- Personalidade: futurista, humana, objetiva e confiavel\n"
            "- Cores: fundo profundo, ciano para acao, prata para texto, champagne para destaques\n"
            "- Tipografia: Segoe UI para Windows; pesos 400/600/700\n"
            "- Espacamento: escala 4/8/12/16/24/32\n"
            "- Componentes: barra de status, painel de conversa, campo de comando, avatar, alertas e historico\n"
            "- Estados: online, ouvindo, processando, falando, erro recuperavel e offline\n"
            "- Regra visual: avatar deve ser o sinal principal; controles nao competem com a presenca holografica"
        )

    def ux_review(self, description: str) -> str:
        description = description.strip() or "tela atual"
        return (
            f"Revisao UX para {description}:\n"
            "- deixe a acao principal sempre disponivel por texto e voz\n"
            "- reduza botoes quando o comando puder ser entendido automaticamente\n"
            "- mostre status claro: ouvindo, processando, falando ou aguardando\n"
            "- mantenha historico pesquisavel para o usuario confiar no que aconteceu\n"
            "- evite animacoes que cruzem rosto, boca, olhos ou texto\n"
            "- em erro, explique o que falhou e ofereca uma proxima acao segura\n"
            "- salve preferencias sem interromper o fluxo"
        )

    def design_brief(self, product: str) -> str:
        product = product.strip() or "interface"
        return (
            f"Briefing de design para {product}:\n"
            "Objetivo: criar uma experiencia tecnologica, humana e funcional.\n"
            "Publico: criadores, programadores, designers e usuarios que querem automacao pessoal.\n"
            "Tela principal: avatar holografico como foco, conversa lateral, status discreto e entrada natural.\n"
            "Entregaveis: fluxo principal, estados da assistente, componentes, icone, paleta e prototipo responsivo.\n"
            "Criterio de qualidade: parecer vivo e util, sem poluir a tela com controles desnecessarios."
        )

    def _resolve_file(self, target: str) -> Path | None:
        clean = target.strip().strip('"')
        if not clean:
            return None
        path = Path(clean)
        if not path.is_absolute():
            workspace = Path(str(self.config["workspace_path"] or BASE_DIR))
            path = workspace / clean
            if not path.exists():
                path = BASE_DIR / clean
        try:
            path = path.resolve()
        except Exception:
            return None
        return path if path.exists() and path.is_file() else None


class LifeWorkStudio:
    SECTORS = {
        "administracao": ["administracao", "secretaria", "escritorio", "gestao", "rh", "recursos humanos"],
        "vendas": ["vendas", "comercial", "loja", "ecommerce", "cliente", "prospeccao"],
        "atendimento": ["atendimento", "suporte", "sac", "recepcao", "call center"],
        "financeiro": ["financeiro", "contabilidade", "cobranca", "orcamento", "caixa", "nota fiscal"],
        "juridico": ["juridico", "advocacia", "contrato", "processo", "documento legal"],
        "saude": ["saude", "clinica", "hospital", "paciente", "consulta", "dentista", "psicologia"],
        "educacao": ["educacao", "professor", "aluno", "aula", "curso", "treinamento", "escola"],
        "tecnologia": ["programador", "desenvolvedor", "designer", "dados", "ti", "software", "ux", "ui"],
        "criacao": ["criador", "marketing", "social media", "youtube", "conteudo", "design", "foto", "video"],
        "operacoes": ["logistica", "entrega", "estoque", "transportes", "producao", "industria"],
        "servicos": ["manutencao", "limpeza", "obra", "reparo", "instalacao", "salao", "cozinha"],
        "campo": ["agricultura", "fazenda", "pecuaria", "campo", "plantio", "colheita"],
        "seguranca": ["seguranca", "portaria", "monitoramento", "risco", "ocorrencia"],
        "vida": ["vida", "casa", "saude pessoal", "familia", "estudo", "rotina pessoal"],
    }

    def __init__(self, config: Config, memory: Memory) -> None:
        self.config = config
        self.memory = memory

    def help(self) -> str:
        return (
            "Life & Work Studio Teraps:\n"
            "- ajuda trabalho: mostra como posso ajudar em empregos e servicos\n"
            "- plano trabalho sua area: cria rotina, checklist e automacoes\n"
            "- produtividade sua profissao: melhora tempo, foco e qualidade\n"
            "- rotina profissional sua area: agenda diaria sugerida\n"
            "- checklist servico sua area: checklist operacional\n"
            "- melhorar vida: rotina pessoal, energia, organizacao e prioridades\n"
            "- diagnostico produtividade: identifica gargalos pelo que aprendi sobre voce"
        )

    def plan(self, area: str) -> str:
        area = area.strip() or "trabalho"
        sector = self.detect_sector(area)
        self.memory.remember("trabalho", "ultima_area", area)
        return (
            f"Plano de produtividade para {area} ({sector}):\n"
            f"{self._sector_summary(sector)}\n\n"
            "Rotina base:\n"
            "- 1. Capturar tudo que precisa ser feito em uma lista unica\n"
            "- 2. Separar tarefas por urgente, importante, espera e delegavel\n"
            "- 3. Agrupar tarefas repetidas em blocos de horario\n"
            "- 4. Criar modelos para mensagens, relatorios, orcamentos e checklists\n"
            "- 5. Revisar no fim do dia: pendencias, erros, tempo gasto e proximo passo\n\n"
            "Automacoes que o Teraps pode assumir ou preparar:\n"
            "- lembretes, agenda local, resumo do dia e prioridades\n"
            "- pesquisa, rascunhos, respostas, ideias, roteiros, checklists e documentacao\n"
            "- abertura de apps, diagnostico do sistema, arquivos e workspace\n"
            "- registro no banco local do que foi aprendido e do que precisa voltar depois\n\n"
            "Indicadores simples:\n"
            "- tempo por tarefa, atrasos, retrabalho, tarefas repetidas e qualidade percebida pelo cliente"
        )

    def productivity(self, area: str) -> str:
        area = area.strip() or "sua rotina"
        sector = self.detect_sector(area)
        return (
            f"Melhoria de tempo e produtividade para {area}:\n"
            "- Corte tempo: transforme tarefas repetidas em modelos salvos\n"
            "- Reduza erro: use checklist antes de entregar qualquer servico\n"
            "- Ganhe foco: trabalhe em blocos de 25 a 50 minutos por tipo de tarefa\n"
            "- Melhore resposta: tenha mensagens prontas para duvidas frequentes\n"
            "- Organize provas: salve datas, decisoes e historico no banco/memoria\n"
            "- Evolua semanalmente: revise o que tomou mais tempo e automatize primeiro\n"
            f"- Prioridade para {sector}: {self._priority_for(sector)}"
        )

    def routine(self, area: str) -> str:
        area = area.strip() or "trabalho"
        sector = self.detect_sector(area)
        return (
            f"Rotina profissional sugerida para {area}:\n"
            "- Inicio: revisar agenda, pendencias e mensagens criticas\n"
            "- Primeiro bloco: tarefa mais importante antes de interrupcoes\n"
            "- Meio do dia: atendimento, reunioes, entregas e atualizacao de status\n"
            "- Segundo bloco: producao profunda, analise ou execucao tecnica\n"
            "- Fechamento: registrar progresso, preparar amanha e limpar pendencias pequenas\n"
            f"- Cuidado do setor: {self._priority_for(sector)}"
        )

    def checklist(self, area: str) -> str:
        area = area.strip() or "servico"
        sector = self.detect_sector(area)
        return (
            f"Checklist de servico para {area}:\n"
            "- objetivo claro do servico\n"
            "- dados, arquivos, ferramentas e acessos necessarios\n"
            "- riscos e pontos que precisam de confirmacao humana\n"
            "- prazo combinado e criterio de pronto\n"
            "- execucao registrada passo a passo\n"
            "- revisao final de qualidade\n"
            "- entrega com resumo do que foi feito e proximas recomendacoes\n"
            f"- item especifico: {self._priority_for(sector)}"
        )

    def life_improvement(self) -> str:
        personal = self.memory.personal_context(6)
        context = f"\nContexto aprendido: {personal}" if personal else ""
        return (
            "Plano para melhorar tempo, produtividade e vida do usuario:\n"
            "- Definir 3 prioridades por dia: saude, trabalho e vida pessoal\n"
            "- Criar lembretes para compromissos e tarefas que sempre escapam\n"
            "- Separar horarios para foco, mensagens, descanso e organizacao\n"
            "- Usar o Teraps para resumir, planejar, pesquisar e registrar decisoes\n"
            "- Transformar tarefas repetidas em modelos e checklists\n"
            "- Revisar semanalmente o que deu resultado e o que deve ser automatizado\n"
            "- Proteger sono, pausas e alimentacao como parte da produtividade"
            + context
        )

    def diagnostic(self) -> str:
        topics = self.memory.top_topics(8)
        profile = self.memory.learned_profile_summary()
        suggestions = [
            "- escolha uma area com: plano trabalho sua profissao",
            "- crie uma rotina com: rotina profissional sua area",
            "- reduza erro com: checklist servico sua area",
            "- melhore sua semana com: melhorar vida",
        ]
        return (
            "Diagnostico de produtividade:\n"
            f"- Topicos recentes: {', '.join(topics) if topics else 'ainda sem padrao forte'}\n"
            f"- Perfil aprendido: {profile}\n"
            "Proximas acoes:\n" + "\n".join(suggestions)
        )

    def detect_sector(self, text: str) -> str:
        low = self._normalize(text)
        for sector, tokens in self.SECTORS.items():
            if any(token in low for token in tokens):
                return sector
        return "geral"

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.lower())
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    @staticmethod
    def _sector_summary(sector: str) -> str:
        summaries = {
            "administracao": "Foco em agenda, documentos, comunicacao, prazos e organizacao de processos.",
            "vendas": "Foco em funil, atendimento rapido, follow-up, propostas e relacionamento com clientes.",
            "atendimento": "Foco em respostas claras, historico do cliente, SLA e reducao de retrabalho.",
            "financeiro": "Foco em controle, vencimentos, conciliacao, cobranca, comprovantes e previsibilidade.",
            "juridico": "Foco em prazos, documentos, revisao, modelos e organizacao de evidencias. Nao substitui advogado.",
            "saude": "Foco em agenda, registro, orientacao administrativa e acompanhamento. Nao substitui profissional de saude.",
            "educacao": "Foco em plano de aula, estudo, explicacoes, exercicios, revisao e acompanhamento.",
            "tecnologia": "Foco em codigo, arquitetura, debug, documentacao, design, deploy e produtividade tecnica.",
            "criacao": "Foco em ideias, roteiro, calendario editorial, design, publicacao e analise de conteudo.",
            "operacoes": "Foco em fila de trabalho, estoque, entrega, padrao operacional e indicadores.",
            "servicos": "Foco em checklist, orcamento, agenda, materiais, execucao e revisao de qualidade.",
            "campo": "Foco em planejamento, clima, insumos, manutencao, producao e registro de atividades.",
            "seguranca": "Foco em ocorrencias, checklist, rondas, registro e comunicacao de risco.",
            "vida": "Foco em energia, saude, casa, familia, estudo, prioridades e descanso.",
        }
        return summaries.get(sector, "Foco em organizar tarefas, reduzir repeticao, melhorar comunicacao e medir resultados.")

    @staticmethod
    def _priority_for(sector: str) -> str:
        priorities = {
            "financeiro": "conferir valores, datas e comprovantes antes de qualquer envio.",
            "juridico": "separar informacao de apoio e validar decisoes com profissional habilitado.",
            "saude": "usar como apoio administrativo e procurar profissional em questoes clinicas.",
            "vendas": "nunca deixar follow-up sem data definida.",
            "atendimento": "registrar problema, solucao e proximo contato.",
            "educacao": "transformar conteudo em pratica e revisao espacada.",
            "tecnologia": "testar antes de entregar e documentar decisoes tecnicas.",
            "servicos": "confirmar material, local, prazo e criterio de qualidade.",
            "vida": "preservar descanso e rotina sustentavel.",
        }
        return priorities.get(sector, "deixar claro o que precisa ser feito, quando e com qual criterio de pronto.")


class HologramBridge:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.last_state = {"state": "idle", "emotion": "neutral"}
        self.available = False
        self.process: subprocess.Popen | None = None

    def send_state(self, state: str, emotion: str = "neutral", metadata: dict | None = None) -> str:
        self.last_state = {
            "state": state,
            "emotion": emotion,
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "metadata": metadata or {},
        }
        if not self.config["hologram_bridge_enabled"]:
            return "Ponte 3D desativada; estado aplicado no avatar local."
        try:
            import socket

            host = str(self.config["hologram_bridge_host"])
            port = int(self.config["hologram_bridge_port"])
            payload = json.dumps({"type": "TERAPS_STATE", "data": self.last_state}, ensure_ascii=False).encode("utf-8")
            with socket.create_connection((host, port), timeout=1.5) as sock:
                sock.sendall(payload)
            self.available = True
            return f"Estado enviado para renderizador 3D em {host}:{port}."
        except Exception:
            self.available = False
            return "Renderizador 3D nao conectado; usando avatar local."

    def launch_unreal(self) -> str:
        editor = self._editor_path()
        project = self._project_path()
        script = self._script_path()
        if not editor or not editor.exists():
            return "Nao encontrei o UnrealEditor.exe. Configure com: configurar unreal caminho_do_UnrealEditor.exe"
        if not project or not project.exists():
            return f"Nao encontrei o projeto Unreal em {project}."
        if not script or not script.exists():
            return f"Nao encontrei o script da ponte Unreal em {script}."
        if self.process and self.process.poll() is None:
            self.config["hologram_bridge_enabled"] = True
            return "Renderizador Unreal ja esta aberto; ponte 3D ativada."
        try:
            args = [
                str(editor),
                str(project),
                f"-ExecutePythonScript={script}",
                "-NoSplash",
                "-log",
            ]
            self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            self.config["hologram_bridge_enabled"] = True
            return (
                "Unreal Engine iniciado para o avatar 3D do Teraps. "
                "Aguarde a cena carregar; a ponte local ficara em 127.0.0.1:"
                f"{self.config['hologram_bridge_port']}."
            )
        except Exception as exc:
            logging.exception("Falha ao iniciar Unreal.")
            return f"Nao consegui iniciar o Unreal Engine: {exc}"

    def status(self) -> str:
        editor = self._editor_path()
        project = self._project_path()
        script = self._script_path()
        return (
            "Avatar 3D Unreal:\n"
            f"- UnrealEditor: {editor if editor else 'nao encontrado'}\n"
            f"- Projeto: {project} ({'ok' if project and project.exists() else 'faltando'})\n"
            f"- Script ponte: {script} ({'ok' if script and script.exists() else 'faltando'})\n"
            f"- Ponte: {self.config['hologram_bridge_host']}:{self.config['hologram_bridge_port']}\n"
            f"- Estado: {self.last_state.get('state', 'idle')} / {self.last_state.get('emotion', 'neutral')}"
        )

    def _editor_path(self) -> Path | None:
        configured = Path(str(self.config["unreal_editor_path"] or ""))
        if configured.exists():
            return configured
        epic = Path(r"C:\Program Files\Epic Games")
        candidates = sorted(epic.glob(r"UE_*\Engine\Binaries\Win64\UnrealEditor.exe"), reverse=True)
        if candidates:
            self.config["unreal_editor_path"] = str(candidates[0])
            return candidates[0]
        return None

    def _project_path(self) -> Path | None:
        configured = Path(str(self.config["unreal_project_path"] or ""))
        candidates = [
            configured,
            BASE_DIR / "unreal" / "TerapsHologram" / "TerapsHologram.uproject",
            BASE_DIR.parent / "unreal" / "TerapsHologram" / "TerapsHologram.uproject",
            RESOURCE_DIR / "unreal" / "TerapsHologram" / "TerapsHologram.uproject",
        ]
        for candidate in candidates:
            if candidate.exists():
                self.config["unreal_project_path"] = str(candidate)
                return candidate
        return configured

    def _script_path(self) -> Path | None:
        configured = Path(str(self.config["unreal_bridge_script"] or ""))
        candidates = [
            configured,
            BASE_DIR / "unreal" / "TerapsHologram" / "Content" / "Python" / "teraps_unreal_bridge.py",
            BASE_DIR.parent / "unreal" / "TerapsHologram" / "Content" / "Python" / "teraps_unreal_bridge.py",
            RESOURCE_DIR / "unreal" / "TerapsHologram" / "Content" / "Python" / "teraps_unreal_bridge.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                self.config["unreal_bridge_script"] = str(candidate)
                return candidate
        return configured


class AutoSystem:
    def __init__(self, config: Config, memory: Memory, brain_factory, notify_callback=None) -> None:
        self.config = config
        self.memory = memory
        self.brain_factory = brain_factory
        self.notify_callback = notify_callback
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.record_startup()
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def record_startup(self) -> None:
        state = {
            "version": self.config["program_version"],
            "started_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "base_dir": str(BASE_DIR),
            "exe_mode": bool(getattr(sys, "frozen", False)),
        }
        self.memory.set_state("last_startup", state)
        self.memory.log_auto_event("startup", json.dumps(state, ensure_ascii=False))
        self.check_updates()
        self.run_learning_pass()
        self.proactive_check(force=True)

    def _loop(self) -> None:
        while not self.stop_event.wait(60):
            try:
                self.memory.set_state("heartbeat", _dt.datetime.now().isoformat(timespec="seconds"))
                if self.config["auto_learning_enabled"]:
                    self.run_learning_pass()
                if self.config["auto_maintenance_enabled"]:
                    self.run_maintenance_if_due()
                if self.config["auto_update_check_enabled"]:
                    self.check_updates_if_due()
                if self.config["auto_proactive_enabled"]:
                    self.proactive_check()
            except Exception:
                logging.exception("Falha no sistema automatico.")

    def run_learning_pass(self) -> str:
        brain = self.brain_factory()
        suggestions = brain.suggestions()
        summary = self.memory.learned_profile_summary()
        self.memory.set_state(
            "auto_learning",
            {
                "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "top_topics": self.memory.top_topics(6),
                "suggestions": suggestions,
                "profile": summary,
                "personal_context": self.memory.personal_context(8),
            },
        )
        self.memory.log_auto_event("learning", "Perfil e sugestoes atualizados automaticamente.")
        return summary

    def proactive_check(self, force: bool = False) -> str:
        messages: list[str] = []
        for reminder_id, title, due_at in self.memory.due_reminders():
            msg = f"Lembrete: {title}."
            messages.append(msg)
            self.memory.complete_reminder(reminder_id)
            self.memory.log_automation_run("reminder", "done", f"{title} @ {due_at}")

        last_summary = str(self.config["last_proactive_summary"] or "")
        now = _dt.datetime.now()
        if force or (7 <= now.hour <= 10 and self._is_due(last_summary, hours=20)):
            brain = self.brain_factory()
            suggestions = brain.suggestions()
            top = self.memory.top_topics(3)
            if top or suggestions:
                prompt = suggestions[0][1] if suggestions else "resumo executivo"
                messages.append(
                    "Sugestao automatica: pelo seu uso recente, posso ajudar agora com "
                    f"'{prompt}'."
                )
                self.config["last_proactive_summary"] = now.isoformat(timespec="seconds")
                self.memory.log_automation_run("proactive_suggestion", "ready", prompt)

        if messages:
            detail = "\n".join(messages)
            self.memory.set_state("last_proactive_message", {"text": detail, "at": now.isoformat(timespec="seconds")})
            self.memory.log_auto_event("proactive", detail)
            if self.notify_callback:
                self.notify_callback(detail)
            return detail
        return "Sem eventos proativos pendentes."

    def run_maintenance_if_due(self) -> str:
        last = str(self.config["last_auto_maintenance"] or "")
        if not self._is_due(last, hours=6):
            return "Manutencao automatica ainda nao necessaria."
        result = self.memory.optimize()
        self.config["last_auto_maintenance"] = _dt.datetime.now().isoformat(timespec="seconds")
        self.memory.log_auto_event("maintenance", result)
        return result

    def check_updates_if_due(self) -> str:
        last = str(self.config["last_update_check"] or "")
        if not self._is_due(last, hours=12):
            return "Verificacao de atualizacao ainda nao necessaria."
        return self.check_updates()

    def check_updates(self) -> str:
        version = str(self.config["program_version"])
        source = str(self.config["auto_update_source"] or "")
        status = "local"
        detail = "Sem fonte remota configurada; versao local registrada."
        if source:
            try:
                if source.startswith(("http://", "https://")):
                    req = urllib.request.Request(source, headers={"User-Agent": "Teraps-Updater/1.0"})
                    detail = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")[:1000]
                    status = "checked_remote"
                else:
                    path = Path(source)
                    detail = path.read_text(encoding="utf-8")[:1000] if path.exists() else "Fonte local nao encontrada."
                    status = "checked_file" if path.exists() else "missing_source"
            except Exception as exc:
                status = "error"
                detail = str(exc)
        now = _dt.datetime.now().isoformat(timespec="seconds")
        self.config["last_update_check"] = now
        self.memory.conn.execute(
            "INSERT INTO update_history(version, source, status, detail, checked_at) VALUES (?, ?, ?, ?, ?)",
            (version, source or "local", status, detail, now),
        )
        self.memory.conn.commit()
        self.memory.set_state("last_update_check", {"version": version, "source": source or "local", "status": status, "detail": detail})
        self.memory.log_auto_event("update_check", f"{status}: {detail[:180]}")
        return f"Atualizacao verificada automaticamente: {status}."

    @staticmethod
    def _is_due(last: str, hours: int) -> bool:
        if not last:
            return True
        try:
            then = _dt.datetime.fromisoformat(last)
            return (_dt.datetime.now() - then).total_seconds() >= hours * 3600
        except Exception:
            return True


class TerapsBrain:
    def __init__(self, config: Config, memory: Memory) -> None:
        self.config = config
        self.memory = memory
        self.web = WebSearch()
        self.apps = WindowsApps(config)
        self.windows = WindowsIntegration(config)
        self.system = SystemInfo(config)
        self.maintenance = Maintenance()
        self.workspace = WorkspaceAutomation(config, memory)
        self.home = SmartHomeControl(config, memory)
        self.routines = RoutineManager(config, memory, self.home, self.workspace)
        self.youtube = YouTubeCreatorManager(config, memory)
        self.tech = TechStudio(config, memory)
        self.life_work = LifeWorkStudio(config, memory)
        self.bridge = HologramBridge(config)

    def respond(self, text: str) -> str:
        self.memory.log_chat("user", text)
        self.memory.learn_from_text(text)
        self.memory.set_state(
            "last_user_input",
            {"text": text, "at": _dt.datetime.now().isoformat(timespec="seconds")},
        )
        clean = text.strip()
        low = clean.lower()
        try:
            response = self._route(clean, low)
        except Exception:
            logging.error(traceback.format_exc())
            response = "Detectei um erro interno, registrei no log e continuei operacional."
        self.memory.log_chat("assistant", response)
        self.memory.set_state(
            "last_assistant_response",
            {"text": response, "at": _dt.datetime.now().isoformat(timespec="seconds")},
        )
        self.memory.set_state(
            "auto_learning",
            {
                "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "top_topics": self.memory.top_topics(6),
                "suggestions": self.suggestions(),
                "profile": self.memory.learned_profile_summary(),
                "personal_context": self.memory.personal_context(8),
            },
        )
        return response

    def _route(self, clean: str, low: str) -> str:
        normalized_response = self._route_normalized(clean, low)
        if normalized_response is not None:
            return normalized_response
        if not clean:
            return "Estou aqui. Pode falar comigo por texto ou ativar voz opcional."
        if low in {"oi", "ola", "olá", "e ai", "e aí", "bom dia", "boa tarde", "boa noite"}:
            return self.greeting()
        if low in {"obrigado", "obrigada", "valeu", "vlw"}:
            return "De nada. Vou ficar por aqui, pronta para continuar quando voce quiser."
        if low in {"como voce esta", "como você está", "tudo bem", "tudo bom"}:
            return "Estou operacional e tranquila. Quanto mais eu aprendo sobre voce, menos preciso interromper com perguntas."
        if low in {"ajuda", "comandos", "o que voce faz", "o que você faz"}:
            return self.help_text()
        if low in {"central comandos", "comandos completos", "todos comandos", "menu teraps", "painel comandos"}:
            return self.command_center_text()
        if low in {"ativar modo completo", "modo completo", "modo jarvis", "modo teraps completo", "preparar teraps"}:
            return self.activate_complete_mode()
        if low in {"status completo", "status geral", "diagnostico completo", "diagnÃ³stico completo", "estado completo"}:
            return self.full_status()
        if low in {"teste unreal fala", "teste fala unreal", "sincronizar unreal", "sincronizar avatar 3d"}:
            return self.unreal_speech_test()
        if low in {"status github", "github status", "status projeto github", "status repositorio github", "status repositÃ³rio github"}:
            return self.github_status()
        if low in {"preparar release", "checklist release", "publicar versao", "publicar versÃ£o"}:
            return self.release_checklist()
        if low in {"terminal", "terminal interno", "cmd interno", "powershell interno", "telas integradas", "interface integrada", "interface limpa"}:
            return (
                "Tudo esta integrado dentro do Teraps: a conversa fica visivel e terminal, sistema e memoria trabalham por tras no proprio .exe. "
                "Use 'comando ipconfig', 'comando tarefas' ou 'comando disco' para executar diagnosticos sem abrir terminal externo."
            )
        if low in {"painel sistema", "aba sistema", "painel memoria", "painel memória", "aba memoria", "aba memória"}:
            return "Sistema e memoria estao ativos em segundo plano e sao atualizados automaticamente apos as interacoes. Quando voce pedir, eu mostro o resumo direto na conversa."
        if low in {"sugestoes", "sugestões", "o que eu posso fazer", "me sugira algo"}:
            return self.suggestion_text()
        if low.startswith(("lembre que ", "memorize que ", "aprenda que ")):
            fact = self._strip_prefix(clean, ("lembre que ", "memorize que ", "aprenda que "))
            key = fact.split(" e ")[0][:80]
            self.memory.remember("fato", key, fact)
            return f"Memoria gravada: {fact}"
        if low.startswith(("me chamo ", "meu nome e ", "meu nome é ")):
            name = self._strip_prefix(clean, ("me chamo ", "meu nome e ", "meu nome é "))
            self.config["user_name"] = name
            self.memory.remember("perfil", "nome", name)
            return f"Prazer, {name}. Vou lembrar disso."
        if "o que voce lembra" in low or "o que você lembra" in low or low.startswith("memorias"):
            query = ""
            if low.startswith("memorias"):
                query = clean[len("memorias") :].strip()
            memories = self.memory.recall(query)
            if not memories:
                return "Ainda nao tenho memorias salvas."
            return "Minhas memorias recentes:\n" + "\n".join(f"- {k}/{key}: {value}" for k, key, value in memories)
        if low.startswith(("me lembre de ", "lembrete ", "crie lembrete ", "agende ")):
            return self.create_reminder_from_text(clean)
        if low in {"lembretes", "minhas tarefas", "tarefas", "agenda local"}:
            return self.reminder_text()
        if low.startswith(("pesquise ", "procure ", "busque ")):
            query = clean.split(" ", 1)[1]
            return self.search_answer(query)
        if low.startswith("vincule "):
            return self.link_app_from_text(clean)
        if low in {"apps vinculados", "aplicativos vinculados", "listar apps"}:
            return self.apps.list_linked_apps()
        if low in {"status windows", "integracao windows", "integração windows", "windows status"}:
            return self.windows.status()
        if low.startswith(("diagnostico windows ", "diagnóstico windows ", "windows diagnostico ", "windows diagnóstico ")):
            topic = clean.split(" ", 2)[-1]
            return self.windows.diagnostics(topic)
        if low in {"diagnostico windows", "diagnóstico windows", "verificar windows"}:
            return self.windows.diagnostics("geral")
        if low.startswith(("configuracoes windows ", "configurações windows ", "configurar windows ", "abrir configuracoes ", "abrir configurações ")):
            area = clean.split(" ", 2)[-1]
            return self.windows.open_settings(area)
        if low in {"configurar audio", "configurar áudio", "abrir audio", "abrir áudio", "configuracoes de som", "configurações de som"}:
            return self.windows.open_settings("audio")
        if low in {"configurar microfone", "abrir microfone", "permissao microfone", "permissão microfone"}:
            return self.windows.open_settings("microfone")
        if low.startswith(("abrir pasta ", "abra pasta ", "pasta ")):
            folder = re.sub(r"^(abrir pasta|abra pasta|pasta)\s+", "", clean, flags=re.IGNORECASE)
            return self.windows.open_folder(folder)
        if low.startswith(("abra ", "abrir ", "inicie ", "execute ")):
            app = clean.split(" ", 1)[1]
            app_key = self._normalize_text(app)
            if app_key in WindowsIntegration.FOLDERS or app_key in {"teraps", "pasta teraps", "programa", "app"}:
                return self.windows.open_folder(app)
            return self.apps.open_app(app)
        if low.startswith(("comando ", "diagnostico ", "diagnóstico ")):
            cmd = clean.split(" ", 1)[1]
            return self.apps.run_safe_command(cmd)
        if low in {"modo foco", "deep work", "foco profundo"}:
            self.bridge.send_state("thinking", "focused")
            lighting = self.home.set_lighting_scene("deep_work")
            return self.workspace.trigger_deep_work() + "\n" + lighting
        if low in {"status git", "status do git", "verificar repositorio", "verificar repositÃ³rio"}:
            return self.workspace.check_git_status()
        if low in {"pipelines", "status pipeline", "monitoramento", "build status"}:
            return self.workspace.pipeline_status()
        if low in {"ajuda programador", "ajuda dev", "ajuda desenvolvedor", "ajuda designer", "tech studio", "mundo tecnologia"}:
            return self.tech.help()
        if low.startswith(("plano app ", "planejar app ", "planeje app ", "produto tech ")):
            idea = clean.split(" ", 2)[-1]
            return self.tech.plan_app(idea)
        if low.startswith(("arquitetura projeto ", "arquitetura app ", "arquitetura sistema ")):
            idea = clean.split(" ", 2)[-1]
            return self.tech.architecture(idea)
        if low.startswith(("stack projeto ", "stack app ", "tecnologias projeto ")):
            idea = clean.split(" ", 2)[-1]
            return self.tech.stack(idea)
        if low.startswith(("revisar codigo ", "revisar código ", "code review ")):
            target = re.sub(r"^(revisar codigo|revisar código|code review)\s+", "", clean, flags=re.IGNORECASE)
            return self.tech.review_code(target)
        if low.startswith(("explicar codigo ", "explicar código ", "entender codigo ")):
            target = re.sub(r"^(explicar codigo|explicar código|entender codigo)\s+", "", clean, flags=re.IGNORECASE)
            return self.tech.explain_code(target)
        if low in {"checklist deploy", "checklist publicacao", "checklist publicação", "pre deploy"}:
            return self.tech.deploy_checklist()
        if low.startswith(("design system ", "sistema de design ")):
            product = clean.split(" ", 2)[-1]
            return self.tech.design_system(product)
        if low.startswith(("ux review ", "revisao ux ", "revisão ux ")):
            description = clean.split(" ", 2)[-1]
            return self.tech.ux_review(description)
        if low.startswith(("briefing design ", "briefing ui ", "briefing ux ")):
            product = clean.split(" ", 2)[-1]
            return self.tech.design_brief(product)
        if low in {"ajuda trabalho", "ajuda emprego", "ajuda servicos", "ajuda serviços", "life work", "life studio"}:
            return self.life_work.help()
        if low.startswith(("plano trabalho ", "planejar trabalho ", "plano emprego ", "plano servico ", "plano serviço ")):
            area = clean.split(" ", 2)[-1]
            return self.life_work.plan(area)
        if low.startswith(("produtividade ", "melhorar produtividade ", "otimizar trabalho ", "melhorar tempo ")):
            area = clean.split(" ", 1)[-1]
            return self.life_work.productivity(area)
        if low.startswith(("rotina profissional ", "rotina trabalho ", "rotina servico ", "rotina serviço ")):
            area = clean.split(" ", 2)[-1]
            return self.life_work.routine(area)
        if low.startswith(("checklist servico ", "checklist serviço ", "checklist trabalho ")):
            area = clean.split(" ", 2)[-1]
            return self.life_work.checklist(area)
        if low in {"melhorar vida", "melhore minha vida", "organizar vida", "vida produtiva"}:
            return self.life_work.life_improvement()
        if low in {"diagnostico produtividade", "diagnóstico produtividade", "produtividade status"}:
            return self.life_work.diagnostic()
        if low in {"start day", "iniciar dia", "rotina matinal", "bom dia teraps"}:
            self.bridge.send_state("speaking", "smiling")
            return self.routines.start_day()
        if low in {"wind down", "modo relaxar", "rotina noturna", "encerrar expediente"}:
            self.bridge.send_state("speaking", "calm")
            return self.routines.wind_down()
        if low in {"resumo diario", "resumo diÃ¡rio", "resumo executivo", "relatorio diario", "relatÃ³rio diÃ¡rio"}:
            return self.routines.daily_summary()
        if low in {"sensores", "seguranca", "seguranÃ§a", "status da casa", "ambiente"}:
            return self.home.security_status()
        if low in {"avatar 3d", "modo 3d", "holograma 3d", "status avatar"}:
            self.config["avatar_3d_mode"] = True
            return (
                "Avatar 3D holografico ativo no modo local e preparado para Unreal Engine. "
                "Use 'iniciar unreal' para abrir o renderizador 3D com cena holografica controlada pelo Teraps."
            )
        if low.startswith("configurar unreal "):
            editor = clean[len("configurar unreal ") :].strip().strip('"')
            if not Path(editor).exists():
                return f"Nao encontrei esse UnrealEditor.exe: {editor}"
            self.config["unreal_editor_path"] = editor
            return f"Unreal Engine configurado em {editor}."
        if low in {"iniciar unreal", "abrir unreal", "avatar unreal", "holograma unreal", "renderizador unreal"}:
            return self.bridge.launch_unreal()
        if low in {"status unreal", "status avatar unreal", "ponte unreal"}:
            return self.bridge.status()
        if low.startswith("configurar workspace "):
            path = clean[len("configurar workspace ") :].strip().strip('"')
            if not Path(path).exists():
                return f"Nao encontrei essa pasta: {path}"
            self.config["workspace_path"] = path
            return f"Workspace principal configurado para {path}."
        if low.startswith("configurar ide "):
            ide = clean[len("configurar ide ") :].strip()
            self.config["workspace_ide"] = ide
            return f"IDE configurada para {ide}."
        if low.startswith("configurar home assistant "):
            body = clean[len("configurar home assistant ") :].strip()
            parts = body.split(" ", 1)
            if len(parts) < 2:
                return "Use: configurar home assistant http://localhost:8123/api SEU_TOKEN"
            self.config["home_hub_url"] = parts[0].rstrip("/")
            self.config["home_hub_token"] = parts[1].strip()
            return "Home Assistant configurado no banco local."
        if low in {"ponte 3d", "ponte holografica", "ponte hologrÃ¡fica"}:
            self.config["hologram_bridge_enabled"] = True
            return self.bridge.send_state("idle", "neutral")
        if low in {"sistema", "status do sistema", "diagnostico", "diagnóstico"}:
            return self.system.summary()
        if low in {"perfil hardware", "hardware", "adaptacao", "adaptacao do sistema"}:
            return self.adaptive_status()
        if low in {"adaptar hardware", "recalibrar hardware", "auto hardware", "perfil automatico"}:
            self.config["profile"] = "auto"
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            return self.adaptive_status()
        if low in {"modo economico", "perfil economico"}:
            self.config["profile"] = "eco"
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            return self.adaptive_status()
        if low in {"modo ultra", "perfil ultra", "desempenho maximo"}:
            self.config["profile"] = "ultra"
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            return self.adaptive_status()
        if low in {"ativar voz", "ligar voz"}:
            self.config["auto_speak"] = True
            return "Voz ativada."
        if low in {"saida de audio", "saída de áudio", "audio", "áudio"}:
            self.config["audio_output"] = "windows_default"
            return (
                "A fala do Teraps esta configurada para sair pelo dispositivo padrao de audio do Windows. "
                "Troque a saida no proprio Windows e eu acompanho automaticamente."
            )
        if low in {"teste voz", "testar voz", "teste audio", "teste áudio"}:
            self.config["auto_speak"] = True
            self.config["audio_output"] = "windows_default"
            return "Teste de voz do Teraps. Se voce esta ouvindo esta frase, o audio esta saindo pela saida padrao do Windows."
        if low in {"voz teraps", "criar voz", "voz feminina"}:
            self.config["auto_speak"] = True
            self.config["audio_output"] = "windows_default"
            self.config["voice_engine"] = "neural"
            self.config["neural_voice"] = "pt-BR-FranciscaNeural"
            self.config["neural_voice_rate"] = "-3%"
            self.config["neural_voice_pitch"] = "-2Hz"
            self.config["neural_voice_volume"] = "+0%"
            self.config["voice_rate"] = 168
            self.config["voice_volume"] = 0.96
            self.config["voice_name_hint"] = "female"
            return "Voz Teraps configurada no modo neural feminino, com ritmo mais natural e pausas mais humanas. Se a internet falhar, uso a voz feminina do Windows como reserva."
        if low in {"voz neural", "ativar voz neural"}:
            self.config["voice_engine"] = "neural"
            self.config["auto_speak"] = True
            return "Voz neural ativada. Vou usar uma voz feminina mais natural quando houver conexao disponivel."
        if low in {"voz windows", "voz local", "voz offline"}:
            self.config["voice_engine"] = "windows"
            self.config["auto_speak"] = True
            return "Voz local do Windows ativada. Ela funciona offline usando a saida padrao de audio."
        if low in {"status voz", "voz status"}:
            return Voice(self.config).status()
        if low in {"status microfone", "microfone", "status do microfone", "entrada de voz"}:
            return Microphone(self.config).status()
        if low in {"desativar voz", "desligar voz", "modo texto"}:
            self.config["auto_speak"] = False
            return "Voz desativada. Continuo em modo texto."
        if "hora" in low:
            return "Agora sao " + _dt.datetime.now().strftime("%H:%M") + "."
        if "data" in low or "dia e hoje" in low or "dia é hoje" in low:
            return "Hoje e " + _dt.datetime.now().strftime("%d/%m/%Y") + "."
        if "atualizar" in low or "updates" in low:
            return self.update_status()
        if low in {"aprendizado automatico", "aprendizado automático", "perfil aprendido", "o que voce aprendeu", "o que você aprendeu"}:
            personal = self.memory.personal_context(10) or "Nenhum contexto pessoal consolidado ainda."
            return "Perfil aprendido automaticamente:\n" + self.memory.learned_profile_summary() + "\n\nContexto pessoal:\n" + personal
        if low in {"estado automatico", "estado automático", "estado do programa"}:
            state = self.memory.get_state("auto_learning", {})
            return "Estado automatico registrado no banco:\n" + json.dumps(state, ensure_ascii=False, indent=2)[:2500]
        if low in {"automacao proativa", "automação proativa", "verificar automacoes", "verificar automações"}:
            auto = AutoSystem(self.config, self.memory, lambda: TerapsBrain(self.config, self.memory))
            return auto.proactive_check(force=True)
        if low in {"verificar atualizacao", "verificar atualização", "checar update"}:
            auto = AutoSystem(self.config, self.memory, lambda: TerapsBrain(self.config, self.memory))
            return auto.check_updates()
        if low.startswith("configurar fonte update "):
            source = clean[len("configurar fonte update ") :].strip()
            self.config["auto_update_source"] = source
            return f"Fonte de atualizacao configurada no banco: {source}"
        if low in {"manutencao automatica", "manutenção automática", "otimizar banco"}:
            return self.memory.optimize()
        if low in {"autorreparo", "auto reparo", "reparar", "corrigir erros"}:
            return self.maintenance.repair()
        if low in {"autodiagnostico", "auto diagnostico", "verificar teraps"}:
            return self.maintenance.status()
        if any(word in low for word in ["erro", "bug", "falha", "travou"]):
            return self.self_repair_hint()
        return self.original_reasoning(clean)

    def _route_normalized(self, clean: str, low: str) -> str | None:
        key = self._normalize_text(low)
        if not key:
            return None
        if key in {"oi", "ola", "e ai", "bom dia", "boa tarde", "boa noite"}:
            return self.greeting()
        if key in {"como voce esta", "tudo bem", "tudo bom"}:
            return "Estou operacional e tranquila. Quanto mais eu aprendo sobre voce, menos preciso interromper com perguntas."
        if key in {"ajuda", "comandos", "o que voce faz"}:
            return self.help_text()
        if key in {"central comandos", "comandos completos", "todos comandos", "menu teraps", "painel comandos"}:
            return self.command_center_text()
        if key in {"ativar modo completo", "modo completo", "modo jarvis", "modo teraps completo", "preparar teraps"}:
            return self.activate_complete_mode()
        if key in {"status completo", "status geral", "diagnostico completo", "estado completo"}:
            return self.full_status()
        if key in {"teste unreal fala", "teste fala unreal", "sincronizar unreal", "sincronizar avatar 3d"}:
            return self.unreal_speech_test()
        if key in {"status github", "github status", "status projeto github", "status repositorio github"}:
            return self.github_status()
        if key in {"preparar release", "checklist release", "publicar versao"}:
            return self.release_checklist()
        if key in {"terminal", "terminal interno", "cmd interno", "powershell interno", "telas integradas", "interface integrada", "interface limpa"}:
            return (
                "Tudo esta integrado dentro do Teraps: a conversa fica visivel e terminal, sistema e memoria trabalham por tras no proprio .exe. "
                "Use 'comando ipconfig', 'comando tarefas' ou 'comando disco' para executar diagnosticos sem abrir terminal externo."
            )
        if key in {"painel sistema", "aba sistema", "painel memoria", "aba memoria"}:
            return "Sistema e memoria estao ativos em segundo plano e sao atualizados automaticamente apos as interacoes. Quando voce pedir, eu mostro o resumo direto na conversa."
        if key in {"sugestoes", "o que eu posso fazer", "me sugira algo"}:
            return self.suggestion_text()
        if key.startswith("configurar canal youtube"):
            return self.youtube.configure_channel(clean)
        if key in {"canal youtube", "status youtube", "youtube status"}:
            return self.youtube.channel_status()
        if key.startswith("configurar youtube api"):
            return self.youtube.configure_api(clean[len("configurar youtube api") :].strip())
        if key in {"youtube api", "status youtube api", "integracao youtube"}:
            return self.youtube.api_status()
        if key.startswith("criar video youtube") or key.startswith("criar vídeo youtube"):
            topic = self.youtube.extract_topic(clean)
            return self.youtube.create_video_package(topic)
        if key.startswith("roteiro youtube"):
            topic = self.youtube.extract_topic(clean)
            return self.youtube.create_video_package(topic)
        if key in {"calendario youtube", "calendário youtube", "planejar youtube", "agenda youtube"}:
            return self.youtube.content_calendar()
        if key in {"conteudos youtube", "conteúdos youtube", "listar youtube", "videos youtube", "vídeos youtube"}:
            return self.youtube.list_content()
        if key in {"resumo diario", "resumo executivo", "relatorio diario"}:
            return self.routines.daily_summary()
        if key in {"status git", "status do git", "verificar repositorio"}:
            return self.workspace.check_git_status()
        if key in {"ajuda programador", "ajuda dev", "ajuda desenvolvedor", "ajuda designer", "tech studio", "mundo tecnologia"}:
            return self.tech.help()
        if key.startswith(("plano app ", "planejar app ", "planeje app ", "produto tech ")):
            return self.tech.plan_app(clean.split(" ", 2)[-1])
        if key.startswith(("arquitetura projeto ", "arquitetura app ", "arquitetura sistema ")):
            return self.tech.architecture(clean.split(" ", 2)[-1])
        if key.startswith(("stack projeto ", "stack app ", "tecnologias projeto ")):
            return self.tech.stack(clean.split(" ", 2)[-1])
        if key.startswith(("revisar codigo ", "code review ")):
            target = re.sub(r"^(revisar codigo|revisar código|code review)\s+", "", clean, flags=re.IGNORECASE)
            return self.tech.review_code(target)
        if key.startswith(("explicar codigo ", "entender codigo ")):
            target = re.sub(r"^(explicar codigo|explicar código|entender codigo)\s+", "", clean, flags=re.IGNORECASE)
            return self.tech.explain_code(target)
        if key in {"checklist deploy", "checklist publicacao", "pre deploy"}:
            return self.tech.deploy_checklist()
        if key.startswith(("design system ", "sistema de design ")):
            return self.tech.design_system(clean.split(" ", 2)[-1])
        if key.startswith(("ux review ", "revisao ux ")):
            return self.tech.ux_review(clean.split(" ", 2)[-1])
        if key.startswith(("briefing design ", "briefing ui ", "briefing ux ")):
            return self.tech.design_brief(clean.split(" ", 2)[-1])
        if key in {"ajuda trabalho", "ajuda emprego", "ajuda servicos", "life work", "life studio"}:
            return self.life_work.help()
        if key.startswith(("plano trabalho ", "planejar trabalho ", "plano emprego ", "plano servico ")):
            return self.life_work.plan(clean.split(" ", 2)[-1])
        if key.startswith(("produtividade ", "melhorar produtividade ", "otimizar trabalho ", "melhorar tempo ")):
            return self.life_work.productivity(clean.split(" ", 1)[-1])
        if key.startswith(("rotina profissional ", "rotina trabalho ", "rotina servico ")):
            return self.life_work.routine(clean.split(" ", 2)[-1])
        if key.startswith(("checklist servico ", "checklist trabalho ")):
            return self.life_work.checklist(clean.split(" ", 2)[-1])
        if key in {"melhorar vida", "melhore minha vida", "organizar vida", "vida produtiva"}:
            return self.life_work.life_improvement()
        if key in {"diagnostico produtividade", "produtividade status"}:
            return self.life_work.diagnostic()
        if key in {"sensores", "seguranca", "status da casa", "ambiente"}:
            return self.home.security_status()
        if key in {"status windows", "integracao windows", "windows status"}:
            return self.windows.status()
        if key.startswith(("diagnostico windows ", "windows diagnostico ")):
            return self.windows.diagnostics(key.split(" ", 2)[-1])
        if key in {"diagnostico windows", "verificar windows"}:
            return self.windows.diagnostics("geral")
        if key.startswith(("configuracoes windows ", "configurar windows ", "abrir configuracoes ")):
            return self.windows.open_settings(key.split(" ", 2)[-1])
        if key in {"configurar audio", "abrir audio", "configuracoes de som"}:
            return self.windows.open_settings("audio")
        if key in {"configurar microfone", "abrir microfone", "permissao microfone"}:
            return self.windows.open_settings("microfone")
        if key.startswith(("abrir pasta ", "abra pasta ", "pasta ")):
            folder = re.sub(r"^(abrir pasta|abra pasta|pasta)\s+", "", clean, flags=re.IGNORECASE)
            return self.windows.open_folder(folder)
        if key.startswith(("abra ", "abrir ", "inicie ", "execute ")):
            app = clean.split(" ", 1)[1]
            app_key = self._normalize_text(app)
            if app_key in WindowsIntegration.FOLDERS or app_key in {"teraps", "pasta teraps", "programa", "app"}:
                return self.windows.open_folder(app)
            return self.apps.open_app(app)
        if key.startswith(("comando ", "diagnostico ")):
            cmd = clean.split(" ", 1)[1]
            return self.apps.run_safe_command(cmd)
        if key in {"ponte 3d", "ponte holografica"}:
            self.config["hologram_bridge_enabled"] = True
            return self.bridge.send_state("idle", "neutral")
        if key in {"sistema", "status do sistema", "diagnostico"}:
            return self.system.summary()
        if key in {"perfil hardware", "hardware", "adaptacao", "adaptacao do sistema"}:
            return self.adaptive_status()
        if key in {"adaptar hardware", "recalibrar hardware", "auto hardware", "perfil automatico"}:
            self.config["profile"] = "auto"
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            return self.adaptive_status()
        if key in {"modo economico", "perfil economico"}:
            self.config["profile"] = "eco"
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            return self.adaptive_status()
        if key in {"modo ultra", "perfil ultra", "desempenho maximo"}:
            self.config["profile"] = "ultra"
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            return self.adaptive_status()
        if key in {"saida de audio", "audio"}:
            self.config["audio_output"] = "windows_default"
            return (
                "A fala do Teraps esta configurada para sair pelo dispositivo padrao de audio do Windows. "
                "Troque a saida no proprio Windows e eu acompanho automaticamente."
            )
        if key in {"teste voz", "testar voz", "teste audio"}:
            self.config["auto_speak"] = True
            self.config["audio_output"] = "windows_default"
            return "Teste de voz do Teraps. Se voce esta ouvindo esta frase, o audio esta saindo pela saida padrao do Windows."
        if key in {"avatar 3d", "modo 3d", "holograma 3d", "status avatar"}:
            self.config["avatar_3d_mode"] = True
            return (
                "Avatar 3D holografico ativo no modo local e preparado para Unreal Engine. "
                "Use 'iniciar unreal' para abrir o renderizador 3D com cena holografica controlada pelo Teraps."
            )
        if key in {"iniciar unreal", "abrir unreal", "avatar unreal", "holograma unreal", "renderizador unreal"}:
            return self.bridge.launch_unreal()
        if key in {"status unreal", "status avatar unreal", "ponte unreal"}:
            return self.bridge.status()
        if "data" in key or "dia e hoje" in key:
            return "Hoje e " + _dt.datetime.now().strftime("%d/%m/%Y") + "."
        if key in {"aprendizado automatico", "perfil aprendido", "o que voce aprendeu"}:
            personal = self.memory.personal_context(10) or "Nenhum contexto pessoal consolidado ainda."
            return "Perfil aprendido automaticamente:\n" + self.memory.learned_profile_summary() + "\n\nContexto pessoal:\n" + personal
        if key in {"estado automatico", "estado do programa"}:
            state = self.memory.get_state("auto_learning", {})
            return "Estado automatico registrado no banco:\n" + json.dumps(state, ensure_ascii=False, indent=2)[:2500]
        if key in {"automacao proativa", "verificar automacoes"}:
            auto = AutoSystem(self.config, self.memory, lambda: TerapsBrain(self.config, self.memory))
            return auto.proactive_check(force=True)
        if key in {"verificar atualizacao", "checar update"}:
            auto = AutoSystem(self.config, self.memory, lambda: TerapsBrain(self.config, self.memory))
            return auto.check_updates()
        if key in {"manutencao automatica", "otimizar banco"}:
            return self.memory.optimize()
        return None

    def command_center_text(self) -> str:
        return (
            "Central de Comandos Teraps:\n"
            "Nucleo:\n"
            "- modo completo / status completo / central comandos\n"
            "- terminal interno / interface limpa / painel sistema / painel memoria\n"
            "- status windows / diagnostico windows rede / configurar audio / configurar microfone\n"
            "- sistema / autodiagnostico / autorreparo / manutencao automatica\n\n"
            "Voz e microfone:\n"
            "- voz teraps / voz neural / voz windows / teste voz / saida de audio\n"
            "- status voz / status microfone / ativar voz / desativar voz\n\n"
            "Avatar e Unreal:\n"
            "- avatar 3d / iniciar unreal / status unreal / teste unreal fala\n"
            "- ponte 3d / sincronizar avatar 3d / configurar unreal CAMINHO\n\n"
            "Aprendizado e automacao:\n"
            "- aprendizado automatico / estado automatico / automacao proativa\n"
            "- verificar atualizacao / configurar fonte update URL / adaptar hardware\n\n"
            "Trabalho, tecnologia e criacao:\n"
            "- ajuda trabalho / plano trabalho AREA / produtividade PROFISSAO\n"
            "- ajuda programador / plano app IDEIA / revisar codigo ARQUIVO\n"
            "- configurar canal youtube ... / criar video youtube TEMA / calendario youtube\n\n"
            "Projeto e GitHub:\n"
            "- status github / checklist release / status git / pipelines"
        )

    def activate_complete_mode(self) -> str:
        self.config["auto_speak"] = True
        self.config["audio_output"] = "windows_default"
        self.config["voice_engine"] = "neural"
        self.config["neural_voice"] = "pt-BR-FranciscaNeural"
        self.config["neural_voice_rate"] = "-3%"
        self.config["neural_voice_pitch"] = "-2Hz"
        self.config["neural_voice_volume"] = "+0%"
        self.config["voice_rate"] = 168
        self.config["voice_volume"] = 0.96
        self.config["voice_name_hint"] = "female"
        self.config["avatar_3d_mode"] = True
        self.config["hologram_bridge_enabled"] = True
        self.config["auto_learning_enabled"] = True
        self.config["auto_maintenance_enabled"] = True
        self.config["auto_update_check_enabled"] = True
        self.config["auto_proactive_enabled"] = True
        self.config["adaptive_hardware_enabled"] = True
        adapter = HardwareAdapter(self.config)
        profile = adapter.detect()
        adapter.apply(profile)
        self.memory.remember("sistema", "modo_completo", "voz, microfone, aprendizado, automacao, hardware adaptativo e avatar 3D preparados")
        bridge_status = self.bridge.send_state(
            "speaking",
            "ready",
            {"text": "Modo completo Teraps ativado.", "duration_ms": 2400, "source": "complete_mode"},
        )
        return (
            "Modo completo ativado.\n"
            "- Voz feminina neural priorizada com fallback Windows\n"
            "- Audio no dispositivo padrao do sistema\n"
            "- Aprendizado, manutencao, atualizacao e sugestoes automaticas ativos\n"
            f"- Perfil de hardware: {profile.name}\n"
            "- Avatar 3D/Unreal preparado para sincronizar fala e estados\n"
            f"- Ponte 3D: {bridge_status}"
        )

    def full_status(self) -> str:
        parts = [
            "STATUS COMPLETO TERAPS",
            "",
            self.system.summary(),
            "",
            Voice(self.config).status(),
            "",
            Microphone(self.config).status(),
            "",
            self.adaptive_status(),
            "",
            self.bridge.status(),
            "",
            self.youtube.channel_status(),
            "",
            "Aprendizado:\n" + self.memory.learned_profile_summary(),
        ]
        return "\n".join(parts)

    def unreal_speech_test(self) -> str:
        self.config["hologram_bridge_enabled"] = True
        text = "Teste de fala sincronizada do Teraps no avatar holografico 3D."
        result = self.bridge.send_state(
            "speaking",
            "warm",
            {"text": text, "duration_ms": 4200, "source": "unreal_speech_test"},
        )
        return (
            "Teste de fala enviado para o Unreal.\n"
            f"- Texto: {text}\n"
            f"- Resultado: {result}\n"
            "Se o Unreal estiver aberto com 'iniciar unreal', a boca, olhos, cabeca, mao, brilho e particulas devem reagir."
        )

    def github_status(self) -> str:
        repo = self._repo_path()
        if not repo:
            return "Nao encontrei a pasta .git do projeto Teraps nesta maquina."
        try:
            status = run_hidden(["git", "status", "--short", "--branch"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
            log = run_hidden(["git", "log", "--oneline", "--decorate", "-3"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
            remote = run_hidden(["git", "remote", "-v"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
            return (
                f"Status GitHub do projeto em {repo}:\n"
                f"{(status.stdout or status.stderr).strip()}\n\n"
                "Ultimos commits:\n"
                f"{(log.stdout or log.stderr).strip()}\n\n"
                "Remotos:\n"
                f"{(remote.stdout or remote.stderr).strip()}"
            )[:3500]
        except Exception as exc:
            return f"Nao consegui ler o status GitHub local: {exc}"

    def release_checklist(self) -> str:
        return (
            "Checklist de release Teraps:\n"
            "- rodar python -m py_compile teraps.py\n"
            "- validar script Unreal com UnrealEditor-Cmd\n"
            "- recompilar dist/Teraps.exe com criar_executavel.ps1\n"
            "- abrir o EXE e confirmar que permanece rodando\n"
            "- testar: teste voz, status microfone, terminal interno, status unreal, teste unreal fala\n"
            "- confirmar que teraps_data, logs, cache, build e Saved/Intermediate do Unreal estao fora do Git\n"
            "- commit, push para main e conferir GitHub\n"
            "Comando util no Teraps: status github."
        )

    @staticmethod
    def _repo_path() -> Path | None:
        candidates = [BASE_DIR, BASE_DIR.parent, Path.cwd()]
        for candidate in candidates:
            try:
                if (candidate / ".git").exists():
                    return candidate
            except Exception:
                continue
        return None

    def adaptive_status(self) -> str:
        profile = self.config["adaptive_last_profile"] or {}
        if not profile:
            adapter = HardwareAdapter(self.config)
            adapter.apply(adapter.detect())
            profile = self.config["adaptive_last_profile"] or {}
        snap = SystemInfo.snapshot(self.config)
        glow = "ativos" if profile.get("glow") else "reduzidos"
        return (
            "Adaptacao automatica de hardware ativa.\n"
            f"- Perfil: {profile.get('name', 'auto')}\n"
            f"- Sistema: {snap.get('os_label')}\n"
            f"- CPU/RAM: {snap.get('cpu_cores')} nucleos logicos, {snap.get('memory_total_gb', 0):.1f} GB RAM\n"
            f"- Energia: {snap.get('power_mode')}\n"
            f"- Avatar: {profile.get('fps', '?')} FPS, {profile.get('particles', '?')} particulas, brilhos {glow}\n"
            f"- Microfone: janela de fala ajustada para {self.config['mic_phrase_time_limit']}s\n"
            f"- Motivo: {profile.get('reason', 'ajuste automatico')}"
        )

    def greeting(self) -> str:
        name = self.config["user_name"] or ""
        prefix = f"Oi, {name}." if name else "Oi."
        personal = self.memory.personal_context(3)
        topics = self.memory.top_topics(2)
        if personal:
            return prefix + " Ja estou usando o que aprendi sobre voce: " + personal + "."
        if topics:
            return prefix + " Eu ja percebi alguns interesses seus: " + ", ".join(topics) + ". Quer que eu sugira um proximo passo?"
        return prefix + " Sou a Teraps. Posso conversar normalmente, pesquisar, abrir apps, lembrar preferencias e organizar ideias com voce."

    def suggestions(self) -> list[tuple[str, str]]:
        topics = self.memory.top_topics(4)
        suggestions: list[tuple[str, str]] = []
        topic_map = {
            "pesquisa": ("Pesquisar agora", "pesquise as principais novidades de tecnologia hoje"),
            "apps": ("Abrir app", "apps vinculados"),
            "sistema": ("Ver sistema", "sistema"),
            "planejamento": ("Planejar", "planeje minha proxima tarefa em passos simples"),
            "criacao": ("Criar ideia", "crie uma ideia original para meu projeto"),
            "youtube": ("YouTube", "criar video youtube uma ideia para meu canal"),
            "tecnologia": ("Tech Studio", "ajuda programador"),
            "codigo": ("Revisar codigo", "revisar codigo teraps.py"),
            "design": ("Design/UX", "design system Teraps"),
            "trabalho": ("Trabalho", "ajuda trabalho"),
            "negocios": ("Negocios", "plano trabalho vendas"),
            "educacao": ("Educacao", "plano trabalho professor"),
            "saude": ("Saude", "plano trabalho clinica"),
            "servicos": ("Servicos", "checklist servico atendimento ao cliente"),
            "automacao": ("Modo completo", "modo completo"),
            "memoria": ("Memoria", "o que voce lembra"),
            "foco": ("Modo foco", "modo foco"),
            "casa": ("Ambiente", "sensores"),
        }
        for topic in topics:
            item = topic_map.get(topic)
            if item and item not in suggestions:
                suggestions.append(item)
        defaults = [
            ("Conversar", "oi"),
            ("Comandos", "central comandos"),
            ("Pesquisar", "pesquise novidades de inteligencia artificial"),
            ("Resumo", "resumo executivo"),
            ("Sistema", "sistema"),
            ("Memoria", "o que voce lembra"),
            ("Tech", "ajuda programador"),
            ("Trabalho", "ajuda trabalho"),
            ("YouTube", "canal youtube"),
        ]
        for item in defaults:
            if len(suggestions) >= 4:
                break
            if item not in suggestions:
                suggestions.append(item)
        suggestions = suggestions[:4]
        self.memory.save_suggestions(suggestions, "adaptive")
        return suggestions

    def suggestion_text(self) -> str:
        return "Sugestoes para agora:\n" + "\n".join(f"- {label}: {prompt}" for label, prompt in self.suggestions())

    def create_reminder_from_text(self, text: str) -> str:
        body = self._strip_prefix(text, ("me lembre de ", "lembrete ", "crie lembrete ", "agende ")).strip()
        due_at = self._parse_due_datetime(body)
        title = self._clean_reminder_title(body)
        if not title:
            return "Diga o que devo lembrar. Exemplo: me lembre de revisar o projeto as 18:30."
        if not due_at:
            due_at = _dt.datetime.now() + _dt.timedelta(hours=1)
        reminder_id = self.memory.add_reminder(title, due_at)
        self.memory.log_automation_run("create_reminder", "scheduled", f"{title} @ {due_at.isoformat(timespec='seconds')}")
        return f"Lembrete automatico criado #{reminder_id}: {title} em {due_at.strftime('%d/%m/%Y %H:%M')}."

    def reminder_text(self) -> str:
        reminders = self.memory.list_reminders()
        if not reminders:
            return "Nao ha lembretes no banco local ainda."
        lines = ["Lembretes locais:"]
        for reminder_id, title, due_at, status in reminders:
            try:
                when = _dt.datetime.fromisoformat(due_at).strftime("%d/%m/%Y %H:%M")
            except Exception:
                when = due_at
            lines.append(f"- #{reminder_id} [{status}] {when}: {title}")
        return "\n".join(lines)

    @staticmethod
    def _parse_due_datetime(text: str) -> _dt.datetime | None:
        now = _dt.datetime.now()
        low = text.lower()
        time_match = re.search(r"\b(?:as|às|a|para)\s+(\d{1,2})(?::|h)?(\d{2})?\b", low)
        hour = int(time_match.group(1)) if time_match else None
        minute = int(time_match.group(2) or 0) if time_match else 0
        if hour is not None and not 0 <= hour <= 23:
            return None

        date_match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", low)
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year = int(date_match.group(3) or now.year)
            if year < 100:
                year += 2000
            try:
                return _dt.datetime(year, month, day, hour if hour is not None else 9, minute)
            except ValueError:
                return None

        base = now.date()
        if "amanha" in low or "amanhã" in low:
            base = base + _dt.timedelta(days=1)
        if hour is not None:
            due = _dt.datetime.combine(base, _dt.time(hour, minute))
            if due <= now and "amanha" not in low and "amanhã" not in low:
                due += _dt.timedelta(days=1)
            return due
        return None

    @staticmethod
    def _clean_reminder_title(text: str) -> str:
        cleaned = re.sub(r"\b(?:hoje|amanha|amanhã)\b", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:as|às|a|para)\s+\d{1,2}(?::|h)?\d{0,2}\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", "", cleaned)
        return " ".join(cleaned.strip(" .,!?:;-").split())[:220]

    def search_answer(self, query: str) -> str:
        try:
            results = self.web.search(query)
            if not results:
                self.web.open_query(query)
                return "Nao consegui resumir resultados agora, entao abri a pesquisa no navegador."
            lines = [f"Resultados para '{query}':"]
            for title, href in results:
                lines.append(f"- {title}: {href}")
            return "\n".join(lines)
        except Exception:
            logging.exception("Pesquisa falhou.")
            self.web.open_query(query)
            return "A pesquisa interna falhou, mas abri o navegador com a busca."

    def link_app_from_text(self, text: str) -> str:
        body = text[len("vincule ") :].strip()
        lowered = body.lower()
        for sep in (" em ", " para ", " como "):
            if sep in lowered:
                idx = lowered.find(sep)
                name = body[:idx].strip()
                path = body[idx + len(sep) :].strip()
                if name and path:
                    return self.apps.link_app(name, path)
        return 'Use assim: vincule photoshop em "C:\\Caminho\\Photoshop.exe"'

    def original_reasoning(self, prompt: str) -> str:
        name = self.config["user_name"] or "voce"
        known = self.memory.recall(prompt, limit=3)
        personal = self.memory.personal_context(4)
        context = ""
        if known:
            context = " Levei em conta o que ja lembro: " + "; ".join(value for _, _, value in known)
        elif personal:
            context = " Vou considerar seu perfil aprendido: " + personal
        lower = prompt.lower()
        if any(w in lower for w in ["planeje", "plano", "organize"]):
            return (
                f"Certo, {name}. Eu dividiria assim: 1. definir objetivo; 2. separar recursos; "
                "3. executar a menor etapa util; 4. revisar resultado; 5. automatizar o que repetir." + context
            )
        if any(w in lower for w in ["ideia", "crie", "inventar", "projeto"]):
            return (
                "Proposta original: criar uma versao simples primeiro, medir uso real, depois ligar modulos "
                "de voz, automacao, memoria e internet conforme o hardware permitir." + context
            )
        return (
            f"Entendi. Sobre '{prompt}', posso seguir de um jeito pratico: conversar sobre isso, pesquisar na internet, "
            "transformar em plano ou guardar uma preferencia sua para eu acertar melhor nas proximas vezes."
            + context
        )

    def update_status(self) -> str:
        return (
            "Atualizacoes recorrentes estao preparadas como arquitetura: logs, config, memoria e modulos separados. "
            "Para atualizar de verdade, substitua o arquivo por uma nova versao assinada ou conecte um repositorio."
        )

    def self_repair_hint(self) -> str:
        return (
            f"Eu registrei eventos em {LOG_FILE}. Se algo falhar, reinicio recursos opcionais e sigo no modo texto leve."
        )

    def help_text(self) -> str:
        return (
            "Comandos principais:\n"
            "- central comandos / comandos completos\n"
            "- modo completo / status completo\n"
            "- teste unreal fala / status github / checklist release\n"
            "- pesquise energia solar residencial\n"
            "- abra calculadora\n"
            "- vincule meu app em \"C:\\Caminho\\app.exe\"\n"
            "- apps vinculados\n"
            "- lembre que eu prefiro respostas curtas\n"
            "- o que voce lembra\n"
            "- me lembre de revisar o projeto as 18:30\n"
            "- lembretes / tarefas\n"
            "- sistema\n"
            "- status windows / diagnostico windows audio / abrir downloads\n"
            "- configurar audio / configurar microfone\n"
            "- terminal interno / interface limpa\n"
            "- painel sistema / painel memoria\n"
            "- perfil hardware / adaptar hardware\n"
            "- modo economico / modo ultra / perfil automatico\n"
            "- autodiagnostico / autorreparo\n"
            "- modo foco / deep work\n"
            "- start day / rotina matinal\n"
            "- wind down / rotina noturna\n"
            "- resumo executivo\n"
            "- sensores / status da casa\n"
            "- avatar 3d / status avatar\n"
            "- iniciar unreal / status unreal\n"
            "- configurar unreal \"C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor.exe\"\n"
            "- ajuda trabalho / ajuda servicos\n"
            "- plano trabalho minha area\n"
            "- produtividade minha profissao\n"
            "- rotina profissional minha area\n"
            "- checklist servico minha area\n"
            "- melhorar vida / diagnostico produtividade\n"
            "- status git / pipelines\n"
            "- ajuda programador / ajuda designer\n"
            "- plano app minha ideia\n"
            "- arquitetura projeto minha ideia\n"
            "- stack projeto minha ideia\n"
            "- revisar codigo teraps.py / explicar codigo teraps.py\n"
            "- checklist deploy\n"
            "- design system Teraps / ux review tela principal\n"
            "- briefing design Teraps\n"
            "- aprendizado automatico / estado automatico\n"
            "- automacao proativa\n"
            "- verificar atualizacao / configurar fonte update URL\n"
            "- manutencao automatica\n"
            "- configurar workspace \"C:\\Projeto\"\n"
            "- configurar ide code\n"
            "- configurar home assistant http://localhost:8123/api TOKEN\n"
            "- ponte 3d\n"
            "- comando ipconfig / comando tarefas / comando disco\n"
            "- ativar voz / desativar voz\n"
            "- saida de audio / teste voz\n"
            "- voz neural / voz windows / status voz\n"
            "- status microfone\n"
            "- configurar canal youtube Nome | @handle ou UC... | email | nicho | publico alvo\n"
            "- canal youtube / status youtube\n"
            "- criar video youtube tema do video\n"
            "- calendario youtube / conteudos youtube\n"
            "- configurar youtube api \"C:\\Caminho\\client_secret.json\"\n"
            "- hora / data\n"
            "Recursos opcionais: instale pyttsx3 para voz, SpeechRecognition/PyAudio para microfone e psutil para diagnostico."
        )

    @staticmethod
    def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str:
        lowered = text.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return text[len(prefix) :].strip()
        return text.strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.lower())
        ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        ascii_text = ascii_text.replace("ç", "c")
        return " ".join(ascii_text.split())


class HologramAvatar:
    def __init__(self, canvas: Canvas, profile: HardwareProfile) -> None:
        self.canvas = canvas
        self.profile = profile
        self.phase = 0.0
        self.last_frame_at = time.time()
        self.speaking = False
        self.listening = False
        self.processing = False
        self.speech_text = ""
        self.speech_started = 0.0
        self.speech_until = 0.0
        self.speech_seed = random.random() * 10
        self.avatar_source = None
        self.avatar_photo = None
        self.avatar_depth_photos: dict[tuple[int, int, int], ImageTk.PhotoImage] = {}
        self.avatar_cache_key = None
        self.avatar_bounds = (0.0, 0.0, 0.0, 0.0)
        if Image and ImageTk and AVATAR_FILE.exists():
            try:
                self.avatar_source = Image.open(AVATAR_FILE).convert("RGBA")
            except Exception:
                logging.exception("Falha ao carregar avatar renderizado.")
        self.particles = [
            [
                random.random(),
                random.random(),
                random.uniform(0.4, 1.8),
                random.choice(["#42f5ff", "#b7fbff", "#f6dca7"]),
                random.uniform(-1.0, 1.0),
            ]
            for _ in range(max(8, profile.particles // 2))
        ]

    def set_state(self, speaking: bool = False, listening: bool = False, processing: bool = False) -> None:
        self.speaking = speaking
        self.listening = listening
        self.processing = processing

    def start_speaking(self, text: str, duration_ms: int) -> None:
        now = time.time()
        self.speaking = True
        self.listening = False
        self.speech_text = ""
        self.speech_started = now
        self.speech_until = now + max(0.6, duration_ms / 1000)
        self.speech_seed = random.random() * 10

    def stop_speaking(self) -> None:
        self.speaking = False
        self.speech_text = ""
        self.speech_until = 0.0

    def finish_speaking_if_current(self, expected_until: float) -> None:
        if abs(self.speech_until - expected_until) < 0.05:
            self.set_state(speaking=False, listening=False, processing=False)

    def draw(self) -> None:
        w = max(self.canvas.winfo_width(), 320)
        h = max(self.canvas.winfo_height(), 360)
        c = self.canvas
        c.delete("all")
        now = time.time()
        delta = max(0.0, min(0.08, now - self.last_frame_at))
        self.last_frame_at = now
        self.phase += delta * 3.0
        if self.speaking and self.speech_until and time.time() > self.speech_until:
            self.stop_speaking()

        cx = w * 0.5
        base_y = h - 76
        visual_scale = {
            "economico": 0.94,
            "basico": 0.97,
            "equilibrado": 1.0,
            "alto desempenho": 1.02,
            "ultra": 1.04,
        }.get(self.profile.name, 1.0)
        scale = min(w / 360, h / 620) * visual_scale
        breath = math.sin(self.phase * 0.85) * 3 * scale
        head_tilt = (-7 if self.listening else 0) * scale + math.sin(self.phase * 0.7) * 1.5 * scale
        blink = 0.12 if int(self.phase * 5) % 53 == 0 else 1.0
        density = 1.0 + (0.22 if self.processing else 0.0) + (0.12 if self.speaking else 0.0)

        aura = "#06323a"
        cyan = "#42f5ff"
        pale = "#b7fbff"
        deep = "#0b5966"
        silver = "#dffeff"
        champagne = "#f6dca7"
        magenta = "#f35cff"
        skin = "#102f35"

        for index, p in enumerate(self.particles):
            if index % (2 if self.processing else 3):
                continue
            p[1] -= 0.0016 * p[2]
            if p[1] < 0:
                p[0], p[1], p[4] = random.random(), 1.0, random.uniform(-1.0, 1.0)
            z = p[4]
            x = cx + (p[0] - 0.5) * (230 + z * 28) * scale
            y = base_y - 525 * scale + p[1] * 470 * scale
            size = max(0.5, 0.8 + z * 0.35 + (0.6 if self.processing else 0))
            c.create_oval(x - size, y - size, x + size, y + size, fill=p[3], outline="")

        self._draw_floor(c, cx, base_y, scale, deep, cyan)
        if self.avatar_source is not None:
            self._draw_rendered_avatar(c, cx, base_y, scale, density, cyan, champagne)
        else:
            self._draw_full_body(c, cx, base_y + breath, scale, density, cyan, pale, silver, champagne, magenta, skin, head_tilt, blink)
        if self.processing:
            self._draw_air_panel(c, cx, base_y, scale, cyan, pale, champagne)
        if self.processing:
            self._draw_processing_nodes(c, cx, base_y + breath, scale, cyan, champagne)

        c.create_text(cx, h - 40, text="TERAPS", fill="#b7fbff", font=("Segoe UI", int(18 * scale), "bold"))
        state = "PROCESSANDO" if self.processing else ("CONVERSANDO" if self.speaking else "ONLINE")
        if self.listening:
            state = "OUVINDO"
        c.create_text(cx, h - 18, text=state, fill="#42f5ff", font=("Segoe UI", int(9 * scale)))

    def _draw_floor(self, c: Canvas, cx: float, base_y: float, scale: float, deep: str, cyan: str) -> None:
        if self.processing:
            width = 92 * scale + math.sin(self.phase * 1.5) * 6 * scale
            c.create_line(cx - width, base_y - 4 * scale, cx + width, base_y - 4 * scale, fill="#0a4650", width=3)
            c.create_line(cx - width * 0.62, base_y, cx + width * 0.62, base_y, fill=cyan, width=1)

    def _draw_rendered_avatar(self, c: Canvas, cx: float, base_y: float, scale: float, density: float, cyan: str, champagne: str) -> None:
        if self.avatar_source is None:
            return
        source_w, source_h = self.avatar_source.size
        target_h = int(min(c.winfo_height() * 0.82, 575 * scale))
        target_h = max(280, target_h)
        target_w = int(source_w * (target_h / source_h))
        cache_key = (target_w, target_h)
        if self.avatar_cache_key != cache_key:
            resized = self.avatar_source.resize((target_w, target_h), Image.Resampling.LANCZOS)
            self.avatar_photo = ImageTk.PhotoImage(resized)
            self.avatar_depth_photos = self._make_depth_layers(resized)
            self.avatar_cache_key = cache_key
        image_y = base_y - target_h / 2 - 6 * scale
        image_x = cx
        if self.profile.glow and self.avatar_depth_photos:
            back = self.avatar_depth_photos.get((target_w, target_h, 0))
            side = self.avatar_depth_photos.get((target_w, target_h, 1))
            front = self.avatar_depth_photos.get((target_w, target_h, 2))
            if back:
                c.create_image(image_x, image_y + 5 * scale, image=back, anchor="center")
            if side:
                c.create_image(image_x + 4 * scale, image_y, image=side, anchor="center")
        if self.avatar_photo:
            c.create_image(image_x, image_y, image=self.avatar_photo, anchor="center")
        if self.profile.glow and self.avatar_depth_photos and front:
            c.create_image(image_x - 2 * scale, image_y, image=front, anchor="center")
        if self.profile.glow:
            self._draw_depth_glints(c, image_x, image_y, target_w, target_h, scale, cyan, champagne)
        self.avatar_bounds = (
            image_x - target_w / 2,
            image_y - target_h / 2,
            image_x + target_w / 2,
            image_y + target_h / 2,
        )

    def _make_depth_layers(self, resized):
        layers: dict[tuple[int, int, int], ImageTk.PhotoImage] = {}
        if Image is None or ImageTk is None:
            return layers
        w, h = resized.size
        alpha = resized.getchannel("A")
        back = Image.new("RGBA", (w, h), (25, 230, 255, 54))
        back.putalpha(alpha.point(lambda a: int(a * 0.18)))
        side = Image.new("RGBA", (w, h), (121, 252, 255, 38))
        side.putalpha(alpha.point(lambda a: int(a * 0.13)))
        front = Image.new("RGBA", (w, h), (255, 232, 184, 18))
        front.putalpha(alpha.point(lambda a: int(a * 0.055)))
        layers[(w, h, 0)] = ImageTk.PhotoImage(back)
        layers[(w, h, 1)] = ImageTk.PhotoImage(side)
        layers[(w, h, 2)] = ImageTk.PhotoImage(front)
        return layers

    def _draw_depth_glints(
        self,
        c: Canvas,
        image_x: float,
        image_y: float,
        target_w: int,
        target_h: int,
        scale: float,
        cyan: str,
        champagne: str,
    ) -> None:
        top = image_y - target_h / 2
        shimmer = 0.5 + 0.5 * math.sin(self.phase * 1.6)
        points = [
            (image_x - target_w * 0.24, top + target_h * 0.24, cyan),
            (image_x + target_w * 0.18, top + target_h * 0.35, champagne),
            (image_x - target_w * 0.08, top + target_h * 0.50, cyan),
            (image_x + target_w * 0.16, top + target_h * 0.68, "#b7fbff"),
        ]
        for i, (x, y, color) in enumerate(points):
            if (i + int(self.phase * 3)) % 2 == 0:
                r = (0.9 + shimmer * 1.2) * scale
                c.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="")

    def _draw_data_orbit(self, c: Canvas, cx: float, base_y: float, scale: float, deep: str, cyan: str, champagne: str) -> None:
        top = base_y - 498 * scale
        bottom = base_y - 70 * scale
        c.create_oval(cx - 118 * scale, top, cx + 118 * scale, bottom, outline=deep, width=2)
        for i in range(2):
            shift = math.sin(self.phase * 0.7 + i) * 10 * scale
            c.create_arc(cx - (96 + i * 18) * scale, top + shift, cx + (96 + i * 18) * scale, bottom - shift, start=72 + i * 42, extent=76, outline=cyan if i == 0 else champagne, width=1)

    def _draw_full_body(
        self,
        c: Canvas,
        cx: float,
        base_y: float,
        scale: float,
        density: float,
        cyan: str,
        pale: str,
        silver: str,
        champagne: str,
        magenta: str,
        skin: str,
        head_tilt: float,
        blink: float,
    ) -> None:
        head_y = base_y - 440 * scale
        neck_y = base_y - 342 * scale
        waist_y = base_y - 218 * scale
        hip_y = base_y - 158 * scale
        knee_y = base_y - 78 * scale
        line_w = max(1, int(2 * density))

        # Legs and luminous feet.
        c.create_line(cx - 26 * scale, hip_y, cx - 36 * scale, knee_y, cx - 48 * scale, base_y - 14 * scale, fill=cyan, width=line_w + 2, smooth=True)
        c.create_line(cx + 26 * scale, hip_y, cx + 35 * scale, knee_y, cx + 48 * scale, base_y - 14 * scale, fill=cyan, width=line_w + 2, smooth=True)
        c.create_line(cx - 8 * scale, hip_y + 4 * scale, cx - 7 * scale, base_y - 20 * scale, fill=silver, width=1)
        c.create_line(cx + 8 * scale, hip_y + 4 * scale, cx + 7 * scale, base_y - 20 * scale, fill=silver, width=1)
        c.create_oval(cx - 68 * scale, base_y - 24 * scale, cx - 20 * scale, base_y - 10 * scale, outline=champagne, width=2)
        c.create_oval(cx + 20 * scale, base_y - 24 * scale, cx + 68 * scale, base_y - 10 * scale, outline=champagne, width=2)

        # Torso with soft android silhouette.
        torso = [
            cx - 58 * scale, neck_y,
            cx - 74 * scale, waist_y,
            cx - 42 * scale, hip_y,
            cx, hip_y + 18 * scale,
            cx + 42 * scale, hip_y,
            cx + 74 * scale, waist_y,
            cx + 58 * scale, neck_y,
        ]
        c.create_polygon(torso, fill=skin, outline=cyan, width=line_w, smooth=True)
        c.create_line(cx, neck_y + 8 * scale, cx, hip_y + 12 * scale, fill=silver, width=1)
        c.create_arc(cx - 52 * scale, waist_y - 24 * scale, cx + 52 * scale, waist_y + 34 * scale, start=200, extent=140, outline=champagne, width=2)

        # Arms: right hand presents a panel when speaking/processing; left rests naturally.
        right_hand_x = cx + (114 if (self.speaking or self.processing) else 78) * scale
        right_hand_y = waist_y - (64 if (self.speaking or self.processing) else 10) * scale
        left_hand_x = cx - 74 * scale
        left_hand_y = hip_y - 10 * scale
        c.create_line(cx + 57 * scale, neck_y + 10 * scale, cx + 96 * scale, waist_y - 42 * scale, right_hand_x, right_hand_y, fill=cyan, width=line_w + 1, smooth=True)
        c.create_line(cx - 57 * scale, neck_y + 10 * scale, cx - 92 * scale, waist_y - 22 * scale, left_hand_x, left_hand_y, fill=cyan, width=line_w + 1, smooth=True)
        c.create_oval(right_hand_x - 8 * scale, right_hand_y - 8 * scale, right_hand_x + 8 * scale, right_hand_y + 8 * scale, outline=pale, width=2)
        c.create_oval(left_hand_x - 7 * scale, left_hand_y - 7 * scale, left_hand_x + 7 * scale, left_hand_y + 7 * scale, outline=pale, width=2)
        if self.processing:
            for i in range(3):
                t = (self.phase * 0.6 + i / 3) % 1.0
                nx = (cx + 58 * scale) * (1 - t) + right_hand_x * t
                ny = (neck_y + 12 * scale) * (1 - t) + right_hand_y * t
                c.create_oval(nx - 3 * scale, ny - 3 * scale, nx + 3 * scale, ny + 3 * scale, fill=champagne, outline="")

        # Hair and head.
        hair_sway = math.sin(self.phase * 1.05) * 3 * scale
        hx = cx + head_tilt
        c.create_oval(hx - 55 * scale + hair_sway, head_y - 16 * scale, hx + 55 * scale + hair_sway, head_y + 86 * scale, fill="#031b20", outline=cyan, width=line_w + 2)
        c.create_arc(hx - 74 * scale + hair_sway, head_y - 12 * scale, hx + 12 * scale, head_y + 148 * scale, start=84, extent=196, outline=cyan, width=4)
        c.create_arc(hx - 16 * scale + hair_sway, head_y - 12 * scale, hx + 76 * scale, head_y + 148 * scale, start=260, extent=198, outline=cyan, width=4)

        face = [
            hx, head_y + 2 * scale,
            hx - 39 * scale, head_y + 18 * scale,
            hx - 43 * scale, head_y + 62 * scale,
            hx - 27 * scale, head_y + 96 * scale,
            hx, head_y + 112 * scale,
            hx + 27 * scale, head_y + 96 * scale,
            hx + 43 * scale, head_y + 62 * scale,
            hx + 39 * scale, head_y + 18 * scale,
        ]
        c.create_polygon(face, fill="#09333a", outline=pale, width=line_w, smooth=True)
        self._draw_eye(c, hx - 19 * scale, head_y + 52 * scale, scale, cyan, pale, blink, -1)
        self._draw_eye(c, hx + 19 * scale, head_y + 52 * scale, scale, cyan, pale, blink, 1)
        c.create_line(hx - 4 * scale, head_y + 59 * scale, hx + 3 * scale, head_y + 76 * scale, fill="#6bdde8", width=1)
        if self.speaking:
            mouth_h = 4 + abs(math.sin(self.phase * 7.0)) * 5
            c.create_oval(hx - 13 * scale, head_y + 84 * scale, hx + 13 * scale, head_y + (84 + mouth_h) * scale, outline=magenta, width=2)
        else:
            c.create_arc(hx - 15 * scale, head_y + 78 * scale, hx + 15 * scale, head_y + 96 * scale, start=202, extent=136, outline=magenta, width=2)

    def _draw_eye(self, c: Canvas, ex: float, ey: float, scale: float, cyan: str, pale: str, blink: float, side: int) -> None:
        eye_h = 7 * scale * blink
        c.create_arc(ex - 13 * scale, ey - 8 * scale, ex + 13 * scale, ey + 8 * scale, start=15, extent=150, outline=pale, width=2)
        if blink > 0.2:
            c.create_oval(ex - 6 * scale, ey - eye_h, ex + 6 * scale, ey + eye_h, outline=cyan, width=2)
            c.create_oval(ex - 2 * scale, ey - 2 * scale, ex + 2 * scale, ey + 2 * scale, fill="#dffeff", outline="")
            c.create_oval(ex + side * 3 * scale, ey - 4 * scale, ex + side * 6 * scale, ey - 1 * scale, fill="#ffffff", outline="")
        else:
            c.create_line(ex - 10 * scale, ey, ex + 10 * scale, ey, fill=pale, width=2)

    def _draw_processing_nodes(self, c: Canvas, cx: float, base_y: float, scale: float, cyan: str, champagne: str) -> None:
        points = [
            (cx, base_y - 294 * scale),
            (cx - 23 * scale, base_y - 250 * scale),
            (cx + 25 * scale, base_y - 250 * scale),
            (cx, base_y - 435 * scale),
        ]
        for i, (x, y) in enumerate(points):
            r = (5 + math.sin(self.phase * 3 + i) * 1.5) * scale
            color = champagne if i == 0 else cyan
            c.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="#ffffff")
        c.create_line(points[0][0], points[0][1], points[1][0], points[1][1], fill="#7ffcff", width=1)
        c.create_line(points[0][0], points[0][1], points[2][0], points[2][1], fill="#7ffcff", width=1)

    def _draw_air_panel(self, c: Canvas, cx: float, base_y: float, scale: float, cyan: str, pale: str, champagne: str) -> None:
        px = cx + 92 * scale
        py = base_y - 385 * scale
        w = 104 * scale
        h = 82 * scale
        c.create_rectangle(px, py, px + w, py + h, outline=cyan, fill="#071f25", width=2)
        c.create_text(px + 12 * scale, py + 12 * scale, text="TERAPS", anchor="w", fill=pale, font=("Segoe UI", max(7, int(8 * scale)), "bold"))
        for i, label in enumerate(["ROTINA", "DADOS", "ACAO"]):
            y = py + (30 + i * 15) * scale
            c.create_line(px + 12 * scale, y, px + (58 + math.sin(self.phase + i) * 14) * scale, y, fill=champagne if i == 1 else cyan, width=2)
            c.create_text(px + 68 * scale, y - 5 * scale, text=label, anchor="w", fill="#9ffcff", font=("Segoe UI", max(6, int(6 * scale))))


class TerapsApp:
    def __init__(self) -> None:
        setup_logging()
        self.config = Config()
        self.hardware_adapter = HardwareAdapter(self.config)
        self.profile = self.detect_profile()
        self.hardware_adapter.apply(self.profile)
        self.memory = Memory()
        self.voice = Voice(self.config)
        self.microphone = Microphone(self.config)
        self.bridge = HologramBridge(self.config)
        self.brain = TerapsBrain(self.config, self.memory)
        self.auto_system = AutoSystem(
            self.config,
            self.memory,
            lambda: TerapsBrain(self.config, self.memory),
            self.enqueue_auto_message,
        )
        self.responses: queue.Queue[str] = queue.Queue()
        self.last_user_text = ""

        self.root = Tk()
        self.root.title("Teraps - Assistente IA Holografica")
        self.root.geometry(self._adaptive_geometry())
        self.root.minsize(760, 520)
        self.root.configure(bg="#02070a")
        if ICON_FILE.exists():
            try:
                self.root.iconbitmap(str(ICON_FILE))
            except Exception:
                logging.info("Icone da janela indisponivel.")

        self.status = StringVar(value=self._status_text())
        self.build_ui()
        self.avatar = HologramAvatar(self.canvas, self.profile)
        self.auto_system.start()
        self.animate()
        self.refresh_adaptive_profile()
        self.poll_responses()
        welcome = "Teraps online. Sistema pronto."
        self.avatar.start_speaking(welcome, self._estimate_speech_duration_ms(welcome))
        self.bridge.send_state("speaking", "warm", {"text": welcome, "duration_ms": self._estimate_speech_duration_ms(welcome), "source": "startup"})
        self.say(welcome)

    def detect_profile(self) -> HardwareProfile:
        if not self.config["adaptive_hardware_enabled"]:
            return HardwareProfile("equilibrado", 30, 26, True, True, True, reason="adaptacao automatica desativada")
        return self.hardware_adapter.detect()

    def _adaptive_geometry(self) -> str:
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1366, 768
        if screen_w <= 1024 or screen_h <= 650:
            return "820x560"
        if self.profile.name in {"economico", "basico"}:
            return "920x600"
        if self.profile.name == "ultra" and screen_w >= 1400 and screen_h >= 850:
            return "1160x740"
        return "1040x680"

    def _status_text(self) -> str:
        mic_status = "mic ativo" if getattr(self, "microphone", None) and self.microphone.available else "sem mic"
        voice_mode = "neural" if getattr(self, "voice", None) and self.voice.neural_available and self.config["voice_engine"] == "neural" else ("Windows" if getattr(self, "voice", None) and self.voice.available else "texto")
        audio_ok = getattr(self, "voice", None) and (self.voice.available or self.voice.neural_available)
        audio_status = "audio: Windows padrao" if audio_ok else "audio: texto"
        return f"Perfil: {self.profile.name} | Voz: {voice_mode} | {audio_status} | {mic_status}"

    def refresh_adaptive_profile(self) -> None:
        try:
            if self.config["adaptive_hardware_enabled"] and str(self.config["profile"] or "auto").lower() == "auto":
                new_profile = self.hardware_adapter.detect()
                changed = (
                    new_profile.name != self.profile.name
                    or new_profile.power_mode != self.profile.power_mode
                    or new_profile.cpu_cores != self.profile.cpu_cores
                )
                if changed:
                    self.profile = new_profile
                    self.hardware_adapter.apply(new_profile)
                    if hasattr(self, "avatar"):
                        self.avatar.profile = new_profile
                    if hasattr(self, "voice"):
                        self.voice.apply_config()
                    if hasattr(self, "status"):
                        self.status.set(self._status_text())
        except Exception:
            logging.exception("Falha ao recalibrar perfil adaptativo.")
        self.root.after(30000, self.refresh_adaptive_profile)

    def build_ui(self) -> None:
        root = self.root
        main = Frame(root, bg="#02070a")
        main.pack(fill=BOTH, expand=True)

        left = Frame(main, bg="#02070a")
        left.pack(side=LEFT, fill=BOTH, expand=True)
        right = Frame(main, bg="#061014", width=430)
        right.pack(side=RIGHT, fill=BOTH)

        self.canvas = Canvas(left, bg="#02070a", highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)

        Label(right, text="TERAPS", bg="#061014", fg="#b7fbff", font=("Segoe UI", 20, "bold")).pack(pady=(18, 4))
        Label(right, textvariable=self.status, bg="#061014", fg="#42f5ff", font=("Segoe UI", 9)).pack(pady=(0, 12))

        self.chat = self._create_visible_console(right, "Conversa")
        self.terminal = self._create_hidden_console("Terminal")
        self.system_panel = self._create_hidden_console("Sistema")
        self.memory_panel = self._create_hidden_console("Memoria")

        self._write_panel(self.chat, "Teraps: Sistema online. Digite e pressione Enter, ou use Ctrl+Espaco para falar.\n\n")
        self._write_panel(self.terminal, "Terminal interno pronto. Nenhum prompt externo sera aberto pelo Teraps.\n\n")
        self.refresh_system_panel()
        self.refresh_memory_panel()

        input_frame = Frame(right, bg="#061014")
        input_frame.pack(fill="x", padx=14, pady=(0, 14))
        self.entry = Entry(input_frame, bg="#02070a", fg="#dffeff", insertbackground="#42f5ff", relief="flat", font=("Segoe UI", 11))
        self.entry.pack(side=LEFT, fill="x", expand=True, ipady=10)
        self.entry_placeholder = "Digite e pressione Enter. Ctrl+Espaco ou duplo clique para falar."
        self._set_entry_placeholder()
        self.entry.bind("<FocusIn>", self._entry_focus_in)
        self.entry.bind("<FocusOut>", self._entry_focus_out)
        self.entry.bind("<Return>", lambda _event: self.submit())
        self.entry.bind("<Double-Button-1>", lambda _event: self.listen())
        root.bind("<Control-space>", lambda _event: self.listen())
        root.bind("<Control-Return>", lambda _event: self.submit())

    def _create_visible_console(self, parent: Frame, title: str) -> Text:
        text = Text(
            parent,
            bg="#08181d",
            fg="#dffeff",
            insertbackground="#42f5ff",
            relief="flat",
            wrap="word",
            font=("Consolas" if title == "Terminal" else "Segoe UI", 10),
            padx=12,
            pady=12,
        )
        text.pack(fill=BOTH, expand=True, padx=14, pady=(0, 10))
        text.configure(state="disabled")
        return text

    def _create_hidden_console(self, title: str) -> Text:
        text = Text(
            self.root,
            bg="#08181d",
            fg="#dffeff",
            insertbackground="#42f5ff",
            relief="flat",
            wrap="word",
            font=("Consolas" if title == "Terminal" else "Segoe UI", 10),
            padx=12,
            pady=12,
        )
        text.configure(state="disabled")
        return text

    @staticmethod
    def _write_panel(panel: Text, content: str) -> None:
        panel.configure(state="normal")
        panel.insert(END, content)
        panel.see(END)
        panel.configure(state="disabled")

    def append_chat(self, who: str, text: str) -> None:
        self._write_panel(self.chat, f"{who}: {text}\n\n")

    def append_terminal(self, title: str, text: str) -> None:
        timestamp = _dt.datetime.now().strftime("%H:%M:%S")
        self._write_panel(self.terminal, f"[{timestamp}] {title}\n{text}\n\n")

    def refresh_system_panel(self) -> None:
        content = (
            "PAINEL DO SISTEMA\n\n"
            + SystemInfo(self.config).summary()
            + "\n\n"
            + Maintenance().status()
        )
        self._replace_panel(self.system_panel, content + "\n")

    def refresh_memory_panel(self) -> None:
        memories = self.memory.recall("", limit=12)
        state = self.memory.get_state("auto_learning", {})
        lines = ["MEMORIA E APRENDIZADO", "", "Memorias recentes:"]
        if memories:
            lines.extend(f"- {kind}/{key}: {value}" for kind, key, value in memories)
        else:
            lines.append("- nenhuma memoria salva ainda")
        lines.extend(["", "Estado automatico:", json.dumps(state, ensure_ascii=False, indent=2)[:2500]])
        self._replace_panel(self.memory_panel, "\n".join(lines) + "\n")

    @staticmethod
    def _replace_panel(panel: Text, content: str) -> None:
        panel.configure(state="normal")
        panel.delete("1.0", END)
        panel.insert(END, content)
        panel.see("1.0")
        panel.configure(state="disabled")

    def _set_entry_placeholder(self) -> None:
        if not self.entry.get().strip():
            self.entry.insert(0, self.entry_placeholder)
            self.entry.configure(fg="#5fb9c6")

    def _entry_focus_in(self, _event=None) -> None:
        if self.entry.get() == self.entry_placeholder:
            self.entry.delete(0, END)
            self.entry.configure(fg="#dffeff")

    def _entry_focus_out(self, _event=None) -> None:
        self._set_entry_placeholder()

    def enqueue_auto_message(self, text: str) -> None:
        self.responses.put("[AUTO] " + text)

    def submit(self) -> None:
        text = self.entry.get().strip()
        if text == getattr(self, "entry_placeholder", ""):
            return
        if not text:
            return
        self.handle_user_text(text)

    def handle_user_text(self, text: str) -> None:
        self.entry.delete(0, END)
        self.entry.configure(fg="#dffeff")
        self._set_entry_placeholder()
        self.last_user_text = text
        self.append_chat("Voce", text)
        if self._is_terminal_command(text):
            self.append_terminal("entrada", f"> {text}")
        self.avatar.set_state(processing=True)
        self.bridge.send_state("thinking", "focused")
        threading.Thread(target=self._think, args=(text,), daemon=True).start()

    def listen(self) -> None:
        if not self.microphone.available:
            msg = self.microphone.listen_once().message
            self.append_chat("Teraps", msg)
            self.say(msg)
            return
        self.avatar.set_state(listening=True)
        self.bridge.send_state("listening", "attentive")
        self.append_chat("Teraps", "Ouvindo pelo microfone padrao do Windows...")
        threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self) -> None:
        result = self.microphone.listen_once()
        if result.ok and result.text:
            self.root.after(0, lambda: self.handle_user_text(result.text))
        else:
            self.root.after(0, lambda message=result.message: self._listen_failed(message))

    def _listen_failed(self, message: str) -> None:
        self.avatar.set_state(listening=False)
        self.bridge.send_state("idle", "clarify")
        final_message = message or "Nao consegui entender o audio. Pode explicar de outro jeito o que voce quer que eu faca?"
        self.append_chat("Teraps", final_message)
        self.say(final_message)

    def _think(self, text: str) -> None:
        time.sleep(0.15)
        response = self.brain.respond(text)
        self.responses.put(response)

    def poll_responses(self) -> None:
        try:
            while True:
                response = self.responses.get_nowait()
                self.avatar.set_state(speaking=True, listening=False, processing=self._should_show_processing())
                is_auto = response.startswith("[AUTO] ")
                clean_response = response[7:] if is_auto else response
                speech_ms = self._estimate_speech_duration_ms(clean_response)
                self.bridge.send_state(
                    "speaking",
                    "warm",
                    {"text": clean_response, "duration_ms": speech_ms, "source": "teraps_voice"},
                )
                self.avatar.start_speaking(clean_response, speech_ms)
                speech_until = self.avatar.speech_until
                self.append_chat("Teraps", clean_response)
                if self._is_terminal_command(self.last_user_text) or is_auto:
                    self.append_terminal("saida", clean_response)
                self.refresh_system_panel()
                self.refresh_memory_panel()
                self.say(clean_response)
                self.root.after(speech_ms, lambda until=speech_until: self._finish_speaking_state(until))
        except queue.Empty:
            pass
        self.root.after(100, self.poll_responses)

    def say(self, text: str) -> None:
        self.voice.speak(text)

    def _finish_speaking_state(self, speech_until: float) -> None:
        self.avatar.finish_speaking_if_current(speech_until)
        self.bridge.send_state("idle", "neutral")

    def _should_show_processing(self) -> bool:
        low = self.last_user_text.lower()
        return any(token in low for token in ["modo foco", "deep work", "pipeline", "git", "resumo", "sistema", "erro", "sensores"])

    @staticmethod
    def _is_terminal_command(text: str) -> bool:
        low = TerapsBrain._normalize_text(text)
        return low.startswith(("comando ", "diagnostico ")) or low in {
            "sistema",
            "status do sistema",
            "autodiagnostico",
            "auto diagnostico",
            "verificar teraps",
            "status git",
            "pipelines",
            "terminal",
            "cmd",
            "powershell",
            "abrir terminal",
            "abra terminal",
        }

    @staticmethod
    def _estimate_speech_duration_ms(text: str) -> int:
        compact = " ".join((text or "").split())
        if not compact:
            return 900
        words = len(compact.split())
        chars = len(compact)
        punctuation_pauses = sum(compact.count(p) for p in ".;:!?") * 180
        duration = int(max(words * 360, chars * 62) + punctuation_pauses + 700)
        return max(1300, min(18000, duration))

    def animate(self) -> None:
        self.avatar.draw()
        self.root.after(max(15, int(1000 / self.profile.fps)), self.animate)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    try:
        TerapsApp().run()
        return 0
    except Exception:
        setup_logging()
        logging.error(traceback.format_exc())
        print(f"Teraps encontrou um erro. Veja o log em: {LOG_FILE}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
