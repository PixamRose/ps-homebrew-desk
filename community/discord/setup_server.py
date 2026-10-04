#!/usr/bin/env python3
"""
Pixam Community — setup automatique du serveur Discord.

Crée rôles, catégories, salons texte/vocal et permissions
pour une communauté PS5 jailbreak / homebrew / apps Pixam.

Usage:
  1. Crée un serveur Discord vide (ex. "Pixam Community")
  2. Crée un bot sur https://discord.com/developers/applications
  3. Invite le bot avec la permission Administrateur
  4. Copie .env.example → .env et renseigne TOKEN + GUILD_ID
  5. python setup_server.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import discord
from discord.ext import commands

ROOT = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(ROOT / ".env")

# ── Config ──────────────────────────────────────────────────────────────────

SERVER_NAME = "Pixam Community"
SERVER_DESCRIPTION = (
    "Communauté officielle by Pixam — jailbreak PS5, news firmware, "
    "homebrew et mises à jour des apps (PS Homebrew Desk & co)."
)

# Couleurs rôles (int RGB)
ROLES = [
    {
        "name": "👑 Pixam",
        "color": 0xE74C3C,
        "hoist": True,
        "permissions": discord.Permissions(administrator=True),
        "key": "owner",
    },
    {
        "name": "🛡️ Modérateur",
        "color": 0x3498DB,
        "hoist": True,
        "permissions": discord.Permissions(
            manage_messages=True,
            kick_members=True,
            ban_members=True,
            mute_members=True,
            move_members=True,
            manage_nicknames=True,
            moderate_members=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            mention_everyone=True,
            connect=True,
            speak=True,
        ),
        "key": "mod",
    },
    {
        "name": "⭐ VIP",
        "color": 0xF1C40F,
        "hoist": True,
        "permissions": discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            connect=True,
            speak=True,
            use_external_emojis=True,
            change_nickname=True,
        ),
        "key": "vip",
    },
    {
        "name": "🎮 Membre",
        "color": 0x2ECC71,
        "hoist": False,
        "permissions": discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            add_reactions=True,
            connect=True,
            speak=True,
            stream=True,
            use_voice_activation=True,
        ),
        "key": "member",
    },
    {
        "name": "📢 Ping News",
        "color": 0x9B59B6,
        "hoist": False,
        "permissions": discord.Permissions.none(),
        "key": "ping_news",
    },
    {
        "name": "🔧 Ping Updates",
        "color": 0x1ABC9C,
        "hoist": False,
        "permissions": discord.Permissions.none(),
        "key": "ping_updates",
    },
    {
        "name": "🚨 Ping JB",
        "color": 0xE67E22,
        "hoist": False,
        "permissions": discord.Permissions.none(),
        "key": "ping_jb",
    },
]

# Structure du serveur : catégories → salons
# type: "text" | "voice" | "forum" | "announcement"
STRUCTURE = [
    {
        "name": "📢 ACCUEIL",
        "channels": [
            {
                "name": "bienvenue",
                "type": "text",
                "topic": "Bienvenue sur le serveur Pixam — présente-toi et lis les règles.",
                "readonly": True,
            },
            {
                "name": "regles",
                "type": "text",
                "topic": "Règles du serveur. À lire avant de poster.",
                "readonly": True,
            },
            {
                "name": "annonces",
                "type": "announcement",
                "topic": "Annonces officielles by Pixam.",
                "readonly": True,
            },
            {
                "name": "roles",
                "type": "text",
                "topic": "Choisis tes rôles de ping (News / Updates / JB).",
                "readonly": True,
            },
        ],
    },
    {
        "name": "📰 NEWS PS5",
        "channels": [
            {
                "name": "news-ps5",
                "type": "text",
                "topic": "Actus Sony / PS5 / store / hardware.",
            },
            {
                "name": "firmware",
                "type": "text",
                "topic": "Versions firmware, changelog, risques d'update.",
            },
            {
                "name": "leaks-rumeurs",
                "type": "text",
                "topic": "Rumeurs et leaks — sourcez et restez prudents.",
            },
        ],
    },
    {
        "name": "🛠️ JAILBREAK & HOMEBREW",
        "channels": [
            {
                "name": "jb-general",
                "type": "text",
                "topic": "Discussions jailbreak PS5 / homebrew en général.",
            },
            {
                "name": "aide-jailbreak",
                "type": "text",
                "topic": "Besoin d'aide pour setup / HEN / FTP ? Pose ta question ici.",
            },
            {
                "name": "etahen-onionhen",
                "type": "text",
                "topic": "etaHEN, OnionHEN, payloads et outils associés.",
            },
            {
                "name": "payloads-tools",
                "type": "text",
                "topic": "Partage et discussion autour des tools / payloads légitimes.",
            },
            {
                "name": "ps4-jb",
                "type": "text",
                "topic": "Coin PS4 jailbreak (si tu viens du 4).",
            },
        ],
    },
    {
        "name": "📱 APPS PIXAM",
        "channels": [
            {
                "name": "mises-a-jour",
                "type": "announcement",
                "topic": "Changelog et releases des apps Pixam.",
                "readonly": True,
            },
            {
                "name": "ps-homebrew-desk",
                "type": "text",
                "topic": "Support & discussion autour de PS Homebrew Desk (Mac / Windows / PWA).",
            },
            {
                "name": "suggestions",
                "type": "forum",
                "topic": "Idées de features pour les apps Pixam.",
            },
            {
                "name": "bugs-reports",
                "type": "forum",
                "topic": "Signale un bug : OS, version app, étapes de repro.",
            },
        ],
    },
    {
        "name": "💬 COMMUNAUTÉ",
        "channels": [
            {
                "name": "general",
                "type": "text",
                "topic": "Salon principal — discussions libres autour de la scène.",
            },
            {
                "name": "presentations",
                "type": "text",
                "topic": "Présente-toi : pseudo, firmware, setup.",
            },
            {
                "name": "media",
                "type": "text",
                "topic": "Screenshots, clips, setups desk / PS5.",
            },
            {
                "name": "off-topic",
                "type": "text",
                "topic": "Tout sauf JB / PS5 / apps — détente.",
            },
        ],
    },
    {
        "name": "🔊 VOCAL",
        "channels": [
            {"name": "Salon général", "type": "voice", "user_limit": 0},
            {"name": "Gaming / chill", "type": "voice", "user_limit": 10},
            {"name": "Support live", "type": "voice", "user_limit": 5},
            {"name": "AFK", "type": "voice", "user_limit": 0},
        ],
    },
    {
        "name": "🔒 STAFF",
        "staff_only": True,
        "channels": [
            {
                "name": "mod-chat",
                "type": "text",
                "topic": "Discussion privée du staff.",
            },
            {
                "name": "mod-logs",
                "type": "text",
                "topic": "Logs / notes de modération.",
            },
            {"name": "Staff vocal", "type": "voice", "user_limit": 0},
        ],
    },
]

RULES_TEXT = """\
# Règles — Pixam Community

1. **Respect** — Pas d'insultes, harcèlement, spam ou pub non autorisée.
2. **Sujets** — JB / homebrew / news PS5 / apps Pixam. Le reste → `#off-topic`.
3. **Pas de piratage** — Pas de liens de dumps, jeux piratés, comptes volés, ou tools clairement illégaux.
4. **Aide claire** — Firmware, HEN utilisé, message d'erreur, ce que tu as déjà tenté.
5. **Spoilers / leaks** — Spoiler les gros leaks et cite ta source.
6. **Pseudo Pixam** — Seul le vrai Pixam porte le rôle 👑. Usurpation = ban.
7. **Mods** — Les modos ont le dernier mot. Conteste en MP, pas en public.

En restant ici tu acceptes ces règles. Bon setup et bienvenue ✌️
"""

WELCOME_TEXT = """\
# Bienvenue sur **Pixam Community** 🎮

Serveur officiel de **Pixam** — jailbreak PS5, news firmware, homebrew et apps.

**Par où commencer ?**
1. Lis `#regles`
2. Prends tes pings dans `#roles`
3. Présente-toi dans `#presentations`
4. Besoin d'aide JB → `#aide-jailbreak`
5. Suivre les apps → `#mises-a-jour` + `#ps-homebrew-desk`

**Liens utiles**
- PS Homebrew Desk : repo GitHub du projet
- Reste **offline PSN** sur console jailbreakée

Amuse-toi bien — by **Pixam**
"""


def _env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        print(f"[!] Variable manquante: {name}", file=sys.stderr)
        print("    Copie .env.example → .env et renseigne TOKEN + GUILD_ID.", file=sys.stderr)
        sys.exit(1)
    return value


async def _find_role(guild: discord.Guild, name: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=name)


async def _find_category(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    return discord.utils.get(guild.categories, name=name)


def _find_in_category(category: discord.CategoryChannel, name: str, kind: str):
    if kind == "voice":
        return discord.utils.get(category.channels, name=name)
    slug = name.lower().replace(" ", "-")
    return discord.utils.get(category.channels, name=slug) or discord.utils.get(
        category.channels, name=name
    )


async def ensure_roles(guild: discord.Guild) -> dict[str, discord.Role]:
    created: dict[str, discord.Role] = {}
    for spec in ROLES:
        existing = await _find_role(guild, spec["name"])
        if existing:
            print(f"  = rôle déjà là : {spec['name']}")
            created[spec["key"]] = existing
            continue
        role = await guild.create_role(
            name=spec["name"],
            colour=discord.Colour(spec["color"]),
            hoist=spec["hoist"],
            mentionable=True,
            permissions=spec["permissions"],
            reason="Setup Pixam Community",
        )
        print(f"  + rôle créé : {spec['name']}")
        created[spec["key"]] = role
        await asyncio.sleep(0.4)
    return created


def _overwrites_for_category(
    guild: discord.Guild,
    roles: dict[str, discord.Role],
    *,
    staff_only: bool = False,
) -> dict:
    everyone = guild.default_role
    overs: dict = {
        everyone: discord.PermissionOverwrite(view_channel=not staff_only),
        roles["member"]: discord.PermissionOverwrite(view_channel=not staff_only),
        roles["vip"]: discord.PermissionOverwrite(view_channel=True),
        roles["mod"]: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            connect=True,
            speak=True,
        ),
        roles["owner"]: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            connect=True,
            speak=True,
        ),
    }
    return overs


def _overwrites_readonly(
    guild: discord.Guild,
    roles: dict[str, discord.Role],
) -> dict:
    overs = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            add_reactions=True,
            read_message_history=True,
        ),
        roles["member"]: discord.PermissionOverwrite(send_messages=False),
        roles["vip"]: discord.PermissionOverwrite(send_messages=False),
        roles["mod"]: discord.PermissionOverwrite(send_messages=True, manage_messages=True),
        roles["owner"]: discord.PermissionOverwrite(send_messages=True, manage_messages=True),
    }
    return overs


async def ensure_structure(guild: discord.Guild, roles: dict[str, discord.Role]) -> dict[str, discord.abc.GuildChannel]:
    channels: dict[str, discord.abc.GuildChannel] = {}

    for cat_spec in STRUCTURE:
        staff_only = bool(cat_spec.get("staff_only"))
        cat_overs = _overwrites_for_category(guild, roles, staff_only=staff_only)
        category = await _find_category(guild, cat_spec["name"])
        if category:
            print(f"  = catégorie : {cat_spec['name']}")
        else:
            category = await guild.create_category(
                cat_spec["name"],
                overwrites=cat_overs,
                reason="Setup Pixam Community",
            )
            print(f"  + catégorie : {cat_spec['name']}")
            await asyncio.sleep(0.5)

        for ch_spec in cat_spec["channels"]:
            name = ch_spec["name"]
            kind = ch_spec["type"]
            existing = _find_in_category(category, name, kind)

            if existing:
                print(f"    = salon : {existing.name}")
                channels[name] = existing
                continue

            overs = None
            if ch_spec.get("readonly") and not staff_only:
                overs = _overwrites_readonly(guild, roles)

            topic = ch_spec.get("topic")
            print(f"    … création de « {name} » ({kind})…", flush=True)
            try:
                ch = await _create_channel(
                    guild,
                    category=category,
                    name=name,
                    kind=kind,
                    topic=topic,
                    overs=overs or cat_overs,
                    user_limit=int(ch_spec.get("user_limit") or 0),
                )
            except discord.HTTPException as exc:
                print(f"    ! échec « {name} » : {exc.status} {exc.text}", flush=True)
                # Fallback texte si annonce/forum refusés (Communauté non activée)
                if kind in ("announcement", "forum"):
                    print(f"    … fallback texte pour « {name} »…", flush=True)
                    ch = await guild.create_text_channel(
                        name,
                        category=category,
                        topic=topic,
                        overwrites=overs or cat_overs,
                        reason="Setup Pixam Community (fallback texte)",
                    )
                else:
                    raise

            print(f"    + salon : {ch.name}", flush=True)
            channels[name] = ch
            # Discord rate-limite fort la création de salons — on ralentit volontairement
            await asyncio.sleep(1.2)

    return channels


async def _create_channel(
    guild: discord.Guild,
    *,
    category: discord.CategoryChannel,
    name: str,
    kind: str,
    topic: str | None,
    overs: dict,
    user_limit: int,
) -> discord.abc.GuildChannel:
    """Crée un salon. Annonce/forum → texte si le serveur n'a pas Communauté."""
    if kind == "voice":
        return await guild.create_voice_channel(
            name,
            category=category,
            user_limit=user_limit,
            overwrites=overs,
            reason="Setup Pixam Community",
        )

    # Sans "Communauté" Discord, news/forum échouent → on part direct en texte
    # (plus fiable pour un serveur tout neuf).
    if kind in ("forum", "announcement"):
        kind = "text"

    return await guild.create_text_channel(
        name,
        category=category,
        topic=topic,
        overwrites=overs,
        reason="Setup Pixam Community",
    )


async def post_starter_messages(
    channels: dict[str, discord.abc.GuildChannel],
    roles: dict[str, discord.Role],
) -> None:
    bienvenue = channels.get("bienvenue")
    regles = channels.get("regles")
    roles_ch = channels.get("roles")

    async def _safe_send(channel, content: str) -> None:
        if not isinstance(channel, discord.TextChannel):
            return
        async for msg in channel.history(limit=20):
            if msg.author.bot and ("Pixam Community" in (msg.content or "") or "Règles" in (msg.content or "")):
                print(f"    = message déjà présent dans #{channel.name}")
                return
        await channel.send(content)
        print(f"    + message posté dans #{channel.name}")
        await asyncio.sleep(0.4)

    if bienvenue:
        await _safe_send(bienvenue, WELCOME_TEXT)
    if regles:
        await _safe_send(regles, RULES_TEXT)
    if roles_ch and isinstance(roles_ch, discord.TextChannel):
        async for msg in roles_ch.history(limit=10):
            if msg.author.bot and "Ping" in (msg.content or ""):
                print("    = message rôles déjà présent")
                break
        else:
            ping_news = roles["ping_news"].mention
            ping_updates = roles["ping_updates"].mention
            ping_jb = roles["ping_jb"].mention
            await roles_ch.send(
                f"# Rôles de ping\n\n"
                f"Réagis ou demande à un modo pour obtenir :\n"
                f"- {ping_news} — actus PS5 / firmware\n"
                f"- {ping_updates} — mises à jour apps Pixam\n"
                f"- {ping_jb} — alertes jailbreak importantes\n\n"
                f"_Astuce staff : assigne les rôles via clic droit → Rôles, "
                f"ou branche un bot de réactions plus tard._"
            )
            print("    + message posté dans #roles")


async def maybe_rename_guild(guild: discord.Guild) -> None:
    if guild.name != SERVER_NAME:
        # Ne force pas le rename si le user a déjà choisi un nom custom
        print(f"  i serveur actuel : « {guild.name} » (pas renommé automatiquement)")
    try:
        await guild.edit(description=SERVER_DESCRIPTION[:120])
    except Exception:
        pass


async def run() -> None:
    token = _env("DISCORD_TOKEN")
    guild_id = int(_env("DISCORD_GUILD_ID"))

    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        guild = bot.get_guild(guild_id)
        if guild is None:
            print(f"[!] Serveur introuvable (id={guild_id}).")
            print("    Vérifie que le bot est bien invité sur le serveur.")
            await bot.close()
            return

        print(f"[*] Connecté : {bot.user} → serveur « {guild.name} »", flush=True)
        print("[*] Création des rôles…", flush=True)
        roles = await ensure_roles(guild)

        print("[*] Création des catégories / salons…", flush=True)
        print("    (si ça pause 10–30s, c'est le rate-limit Discord — normal)", flush=True)
        channels = await ensure_structure(guild, roles)

        print("[*] Messages d'accueil…", flush=True)
        await post_starter_messages(channels, roles)

        await maybe_rename_guild(guild)

        # Donne le rôle Pixam au propriétaire du serveur si possible
        try:
            owner = guild.owner
            if owner and roles.get("owner") and roles["owner"] not in owner.roles:
                await owner.add_roles(roles["owner"], reason="Setup Pixam Community")
                print(f"[*] Rôle 👑 Pixam donné à {owner}")
        except Exception as exc:
            print(f"[!] Impossible d'assigner le rôle owner : {exc}")

        print()
        print("✅ Serveur Pixam Community prêt.")
        print("   Prochaine étape : invite ta communauté + personnalise l'icône / bannière.")
        await bot.close()

    try:
        await bot.start(token)
    except discord.LoginFailure:
        print("[!] Token Discord invalide.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if sys.version_info < (3, 10):
        print("[!] Python 3.10+ requis.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(run())


if __name__ == "__main__":
    main()
