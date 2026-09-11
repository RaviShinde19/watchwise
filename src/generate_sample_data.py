"""
Generates a synthetic watch-history.json that mimics the structure of a real
Google Takeout YouTube export, so the pipeline can be developed/tested without
needing a real export first.

Real Takeout records look like:
{
  "header": "YouTube",
  "title": "Watched Some Video Title",
  "titleUrl": "https://www.youtube.com/watch?v=abc123",
  "subtitles": [{"name": "Some Channel", "url": "https://www.youtube.com/channel/xyz"}],
  "time": "2024-05-01T14:32:07.123Z",
  "products": ["YouTube"],
  "activityControls": ["YouTube watch history"]
}
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

CHANNELS = {
    "CS Dojo": ("productive", ["Python Tutorial for Beginners", "How Binary Search Works", "Data Structures Explained"]),
    "freeCodeCamp": ("productive", ["Learn SQL in 4 Hours", "Full Airflow Course", "Docker Crash Course"]),
    "Fireship": ("productive", ["100 Seconds of Postgres", "Airflow in 100 Seconds", "System Design Basics"]),
    "Veritasium": ("productive", ["Why Machines That Bend Don't Break", "The Physics of Traffic"]),
    "Lex Fridman Podcast": ("neutral", ["Conversation on AI Safety", "Talking Systems Thinking"]),
    "Lofi Girl": ("neutral", ["lofi hip hop radio - beats to relax/study to"]),
    "MKBHD": ("neutral", ["Testing the Newest Phone", "The Best Laptop Right Now"]),
    "PewDiePie": ("entertainment", ["Reacting to Memes", "Playing a Horror Game"]),
    "MrBeast": ("entertainment", ["Last To Leave Wins $100,000", "I Gave Away a Private Island"]),
    "Dude Perfect": ("entertainment", ["Trick Shot Battle", "Overtime Challenge"]),
    "Vine Compilation Central": ("entertainment", ["Try Not To Laugh Challenge", "Funniest Shorts Compilation"]),
}

CHANNEL_NAMES = list(CHANNELS.keys())


def weighted_hour():
    """Skew watch events toward evening (productivity dips) and lunch break."""
    buckets = (
        [9, 10, 11] * 2      # morning study
        + [13, 14] * 2        # lunch
        + [19, 20, 21, 22] * 5  # evening binge zone
        + [23, 0, 1] * 3      # late night
        + list(range(2, 9))   # rare early hours
    )
    return random.choice(buckets)


def generate_events(n_days=60, avg_events_per_day=12):
    events = []
    start = datetime(2024, 1, 1)
    for day_offset in range(n_days):
        day = start + timedelta(days=day_offset)
        n_events = max(1, int(random.gauss(avg_events_per_day, 4)))

        # occasionally create a "binge session": several videos back-to-back
        if random.random() < 0.3:
            channel = random.choice(CHANNEL_NAMES)
            _, titles = CHANNELS[channel]
            hour = weighted_hour()
            base_time = day.replace(hour=hour, minute=random.randint(0, 59))
            for i in range(random.randint(3, 6)):
                t = base_time + timedelta(minutes=i * random.randint(4, 9))
                events.append(make_event(channel, titles, t))
            n_events = max(0, n_events - 4)

        for _ in range(n_events):
            channel = random.choice(CHANNEL_NAMES)
            _, titles = CHANNELS[channel]
            hour = weighted_hour()
            t = day.replace(
                hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59)
            )
            events.append(make_event(channel, titles, t))

    events.sort(key=lambda e: e["time"])
    return events


def make_event(channel, titles, dt):
    title = random.choice(titles)
    video_id = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=11))
    channel_id = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=12))
    return {
        "header": "YouTube",
        "title": f"Watched {title}",
        "titleUrl": f"https://www.youtube.com/watch?v={video_id}",
        "subtitles": [
            {
                "name": channel,
                "url": f"https://www.youtube.com/channel/{channel_id}",
            }
        ],
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "products": ["YouTube"],
        "activityControls": ["YouTube watch history"],
    }


def main():
    out_path = Path(__file__).resolve().parent.parent / "data" / "watch-history.json"
    events = generate_events()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Generated {len(events)} synthetic watch events -> {out_path}")


if __name__ == "__main__":
    main()
