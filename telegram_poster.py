import random
import time
import requests
import logging
import os
import json
import glob
from datetime import datetime, timezone

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Configuration (set as Railway environment variables) ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@YourChannelOrGroup")

# Your personal Telegram user ID — bot sends you DM notifications
# Find it: message @userinfobot on Telegram
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

# The actual URL (can be a UTM / tracking link)
LINK_URL = os.environ.get("LINK_URL", "https://onlyfans.com/yourmodel")
# The clickable hyperlink text shown in Telegram
LINK_TITLE = os.environ.get("LINK_TITLE", "my OnlyFans 💋")

# Posting frequency: random interval between these bounds (in hours)
MIN_INTERVAL_HOURS = int(os.environ.get("MIN_INTERVAL_HOURS", "24"))   # 1 day
MAX_INTERVAL_HOURS = int(os.environ.get("MAX_INTERVAL_HOURS", "72"))   # 3 days

# Folder containing images
IMAGES_FOLDER = os.environ.get("IMAGES_FOLDER", "images")

# Persistent state file
STATE_FILE = "state.json"

# ─── Caption pools ───────────────────────────────────────────────

TEASE_LINES = [
    "feeling a little lonely tonight… 😏",
    "can't sleep… wanna keep me company? 👀",
    "bored and looking for trouble 😈",
    "thinking about you rn… 💭",
    "come say hi, I don't bite… much 😘",
    "who's up? 👀🔥",
    "just took this and had to share 😌",
    "missing you already 💋",
    "wanna see more? you know where to find me 😉",
    "this is just the preview 🤭",
    "late nights hit different… 🌙",
    "I've been waiting for you 👀",
    "dare you to come find me 😏",
    "getting ready for bed… or am I? 😈",
    "guess what I'm wearing rn 🤫",
    "felt cute, might delete later 💅",
    "your favorite girl is online 💋",
    "tell me something sweet 🍒",
    "new content just dropped… don't miss out 🔥",
    "you're not gonna want to miss this one 👀",
    "craving some attention tonight 🥰",
    "hey stranger… where have you been? 😘",
    "come keep me warm 🫦",
    "I saved something special just for you 💌",
    "up late again… entertain me? 😏",
    "the things I'd tell you if you were here… 👀",
    "feeling extra flirty today 💕",
    "sneak peek 😉 the full version is waiting",
    "don't be shy, I like the attention 🤭",
    "this outfit won't stay on for long… 🔥",
]

CTA_LINES = [
    "come see more 👉 {hyperlink}",
    "come chat to me, I'm online 😘 {hyperlink}",
    "come see it here 👉 {hyperlink}",
    "come see why I'm online 😏 {hyperlink}",
    "👉 {hyperlink}",
    "come find out 👀 {hyperlink}",
    "the rest is waiting for you 👉 {hyperlink}",
    "let's talk here 💬 {hyperlink}",
    "come say hi 😉 {hyperlink}",
    "see more of me here 👉 {hyperlink}",
    "don't just look… come play 😈 {hyperlink}",
    "I'm waiting for you here 💋 {hyperlink}",
    "click if you dare 😏 👉 {hyperlink}",
    "the good stuff is here 🔥 {hyperlink}",
    "come keep me company 🥰 {hyperlink}",
]


# ─── State management ─────────────────────────────────────────────

def load_state() -> dict:
    """Load persistent state from disk."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data.get("used_images"), list):
                data["used_images"] = []
            if not isinstance(data.get("next_post_ts"), (int, float)):
                data["next_post_ts"] = 0
            if not isinstance(data.get("post_count"), int):
                data["post_count"] = 0
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load state file, starting fresh: {e}")
    return {"used_images": [], "next_post_ts": 0, "post_count": 0}


def save_state(state: dict):
    """Atomically write state to disk."""
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except IOError as e:
        logger.error(f"Failed to save state: {e}")


# ─── Image handling ───────────────────────────────────────────────

def get_all_images() -> list[str]:
    """Return sorted list of image filenames in IMAGES_FOLDER."""
    extensions = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif")
    images = []
    for ext in extensions:
        images.extend(glob.glob(os.path.join(IMAGES_FOLDER, ext)))
    return sorted([os.path.basename(p) for p in images])


def pick_image(state: dict) -> str | None:
    """Pick a random unused image. Resets cycle when all used."""
    all_images = get_all_images()
    if not all_images:
        logger.error(f"No images found in '{IMAGES_FOLDER}/' folder!")
        return None

    # Clean stale entries (images removed from disk)
    valid_used = [img for img in state["used_images"] if img in all_images]
    if len(valid_used) != len(state["used_images"]):
        logger.info(f"Cleaned {len(state['used_images']) - len(valid_used)} stale entries")
        state["used_images"] = valid_used

    available = [img for img in all_images if img not in set(state["used_images"])]

    if not available:
        logger.info(f"All {len(all_images)} images used — resetting cycle.")
        state["used_images"] = []
        save_state(state)
        available = all_images

    chosen = random.choice(available)
    return os.path.join(IMAGES_FOLDER, chosen)


# ─── Admin notifications ─────────────────────────────────────────

def notify_admin(text: str):
    """Send a status DM to the admin. Logs success/failure."""
    if not ADMIN_CHAT_ID:
        logger.info(f"Admin notification (no ADMIN_CHAT_ID set): {text}")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            data={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info("Admin notification sent successfully.")
        else:
            logger.warning(f"Admin notification failed ({resp.status_code}): {resp.text[:300]}")
    except Exception as e:
        logger.warning(f"Could not notify admin: {e}")


# ─── Caption generation ──────────────────────────────────────────

def generate_caption() -> str:
    """Two-line caption: tease + CTA with clickable hyperlink."""
    tease = random.choice(TEASE_LINES)
    hyperlink = f'<a href="{LINK_URL}">{LINK_TITLE}</a>'
    cta = random.choice(CTA_LINES).format(hyperlink=hyperlink)
    return f"{tease}\n{cta}"


# ─── Posting ──────────────────────────────────────────────────────

def post_message(state: dict) -> bool:
    """Pick an image, generate caption, send to Telegram."""
    image_path = pick_image(state)
    if image_path is None:
        return False

    image_filename = os.path.basename(image_path)
    caption = generate_caption()

    logger.info(f"Posting image: {image_filename}")
    logger.info(f"Caption:\n{caption}")

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(image_path, "rb") as photo:
            resp = requests.post(
                url,
                data={"chat_id": CHANNEL_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": photo},
                timeout=60,
            )

        if resp.status_code != 200:
            logger.error(f"Telegram API {resp.status_code}: {resp.text[:500]}")
            return False

        # Success — mark used
        state["used_images"].append(image_filename)
        state["post_count"] = state.get("post_count", 0) + 1
        save_state(state)

        all_images = get_all_images()
        logger.info(
            f"✅ Post #{state['post_count']} — '{image_filename}' — "
            f"{len(state['used_images'])}/{len(all_images)} used"
        )

        notify_admin(
            f"📸 <b>Post #{state['post_count']}</b> sent!\n"
            f"Image: {image_filename}\n"
            f"Cycle: {len(state['used_images'])}/{len(all_images)} images used"
        )
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram API error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False


# ─── Scheduling (random 24–72h interval) ─────────────────────────

def schedule_next(state: dict):
    """Set the next post time to a random point between MIN and MAX hours from now."""
    hours = random.uniform(MIN_INTERVAL_HOURS, MAX_INTERVAL_HOURS)
    next_ts = time.time() + (hours * 3600)
    state["next_post_ts"] = next_ts
    save_state(state)

    next_dt = datetime.fromtimestamp(next_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info(f"⏰ Next post in {hours:.1f}h (at {next_dt})")

    notify_admin(f"⏰ Next post in {hours:.1f}h — {next_dt}")


def is_due(state: dict) -> bool:
    return time.time() >= state.get("next_post_ts", 0)


# ─── Main loop ────────────────────────────────────────────────────

def main():
    logger.info("=" * 50)
    logger.info("Telegram OF Poster — starting up")
    logger.info("=" * 50)

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN not set!")
        return
    if CHANNEL_ID == "@YourChannelOrGroup":
        logger.warning("CHANNEL_ID looks like the default — check it.")

    state = load_state()

    all_images = get_all_images()
    logger.info(f"Found {len(all_images)} images in '{IMAGES_FOLDER}/'")
    logger.info(f"Images used this cycle: {len(state['used_images'])}/{len(all_images)}")
    logger.info(f"Total posts ever: {state.get('post_count', 0)}")
    logger.info(f"Posting interval: {MIN_INTERVAL_HOURS}–{MAX_INTERVAL_HOURS}h (random)")

    if not all_images:
        logger.error("No images found! Add images to 'images/' folder and redeploy.")
        notify_admin(
            "❌ <b>Bot started but NO IMAGES found!</b>\n"
            "Add images to the 'images/' folder and redeploy."
        )
        return

    # ── Startup notification ──
    notify_admin(
        f"🟢 <b>Bot started!</b>\n"
        f"Images: {len(all_images)} found\n"
        f"Cycle: {len(state['used_images'])}/{len(all_images)} used\n"
        f"Total posts: {state.get('post_count', 0)}\n"
        f"Interval: {MIN_INTERVAL_HOURS}–{MAX_INTERVAL_HOURS}h random"
    )

    # ── Always post on startup to confirm bot is working ──
    logger.info("🚀 Startup post — posting now to confirm bot is working.")
    success = post_message(state)
    if success:
        logger.info("✅ Startup post successful.")
    else:
        logger.warning("⚠️ Startup post failed — will retry at scheduled time.")

    # ── Schedule next post (random 24–72h from now) ──
    schedule_next(state)

    # ── Main loop ──
    last_heartbeat = time.time()
    while True:
        try:
            if is_due(state):
                logger.info("⏰ Post is due — executing...")
                success = post_message(state)
                if success:
                    schedule_next(state)
                else:
                    state["next_post_ts"] = time.time() + 600
                    save_state(state)
                    logger.warning("Post failed — retrying in 10 minutes.")
                    notify_admin("⚠️ Post failed — retrying in 10 minutes.")

            # Heartbeat every 6 hours
            if time.time() - last_heartbeat > 21600:
                next_ts = state.get("next_post_ts", 0)
                next_dt = datetime.fromtimestamp(next_ts, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
                hours_left = max(0, (next_ts - time.time()) / 3600)
                all_imgs = get_all_images()
                logger.info(
                    f"💓 Heartbeat — next post at {next_dt} ({hours_left:.1f}h) | "
                    f"images: {len(state['used_images'])}/{len(all_imgs)} used | "
                    f"posts: {state.get('post_count', 0)}"
                )
                last_heartbeat = time.time()

            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
