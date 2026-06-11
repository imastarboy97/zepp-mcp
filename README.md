# zepp-mcp 🏃

**Connect your Amazfit / Zepp watch to Claude. Free and open-source.**

Ask Claude things like:
- *"When was I most stressed this week?"*
- *"Show my hourly stress breakdown for yesterday"*
- *"How has my sleep been this month?"*
- *"What time of day am I consistently most stressed?"*

---

## How it works

Your Amazfit watch syncs to the Zepp app → which stores data on Huami's servers.
This MCP server reads that data and gives Claude tools to analyze it.

**Stress scores** come directly from your watch's sensor (same data as the Zepp app).
Older devices fall back to a heart rate variability proxy.

---

## Setup (3 steps)

### 1. Install

```bash
git clone https://github.com/your-username/zepp-mcp
cd zepp-mcp
pip install -e .
```

### 2. Add to Claude Desktop

Open `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "zepp-health": {
      "command": "/full/path/to/zepp-mcp/.venv/bin/zepp-mcp",
      "env": {
        "ZEPP_EMAIL":    "your@email.com",
        "ZEPP_PASSWORD": "yourpassword"
      }
    }
  }
}
```

> Get the full path by running `which zepp-mcp` after install.

### 3. Restart Claude Desktop

Quit completely (Cmd+Q) and reopen. Done — Claude now has access to your health data.

---

## Available tools

| Tool | What it does |
|------|-------------|
| `analyze_stress` | Stress analysis for past N days with time-of-day patterns |
| `get_sleep` | Sleep stages, duration, and steps per night |
| `get_heart_rate` | Daily avg/min/max heart rate |
| `get_today_overview` | Quick snapshot: steps, HR, stress, last night's sleep |

---

## Example questions

```
When was I most stressed this week?
Show my hourly stress breakdown for the past 3 days
How has my sleep been this month?
What's my resting heart rate trend this week?
Was I more stressed on weekdays or weekends?
```

---

## Supported devices

Any Amazfit watch or band that syncs with the Zepp app:
GTR, GTS, T-Rex, Bip, Band series, and Mi Band (via Zepp Life).

---

## How auth works

On first run, the server logs in with your email + password and caches the token
in `~/.zepp_mcp_token`. If the token expires, it refreshes automatically.
Your credentials never leave your machine — they're only sent to Huami's servers
(the same as the official Zepp app).

---

## Contributing

PRs welcome! Ideas:
- SPO2 / blood oxygen tool
- Workout history
- Export to CSV

---

## Credits

- [bentasker/zepp_to_influxdb](https://github.com/bentasker/zepp_to_influxdb) — reverse-engineered API endpoints
- [micw/hacking-mifit-api](https://github.com/micw/hacking-mifit-api) — original auth flow
- [argrento/huami-token](https://codeberg.org/argrento/huami-token) — 2025 AES auth
