# Discord Gantt Automation

## What You Get

1. Discord-friendly pseudo-Gantt message (markdown/code block bars).
2. Real PNG Gantt chart image.
3. Mention-triggered generation via bot command.

## Source of Truth

Edit milestone schedule here:
- `ops/planning/gantt/milestone_schedule.json`

## Post Both Markdown + PNG to `#milestones-gantt`

```bash
cd /Users/aleccandidato/Projects/luvatrix
export DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
export DISCORD_GUILD_ID=1476402922827812995
./ops/discord/scripts/post_gantt_to_discord.sh
```

This posts:
1. A pseudo-Gantt markdown block (Discord-native).
2. A generated PNG Gantt chart.

## Generate Full Detailed ASCII Gantt (Includes Completed Milestones)

```bash
cd /Users/aleccandidato/Projects/luvatrix
python ops/discord/scripts/generate_gantt_ascii_detailed.py
cat ops/planning/gantt/milestones_gantt_detailed.md
```

Custom output path:

```bash
python ops/discord/scripts/generate_gantt_ascii_detailed.py \
  --schedule ops/planning/gantt/milestone_schedule.json \
  --out ops/planning/gantt/milestones_gantt_detailed.md
```

## Mention-Driven PNG Generation

Install dependency once:

```bash
python -m pip install discord.py matplotlib
```

Run bot listener:

```bash
cd /Users/aleccandidato/Projects/luvatrix
export DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
python ops/discord/scripts/discord_gantt_mention_bot.py
```

In Discord, mention the bot with:

```text
@Luvatrix Ops Bot gantt render
```

Optional inline override schedule (JSON code block):

~~~text
@Luvatrix Ops Bot gantt render
```json
{
  "title": "Temporary schedule",
  "baseline_start_date": "2026-02-23",
  "milestones": [
    {"id":"M-001","name":"Example","start_week":1,"end_week":2,"status":"In Progress"}
  ]
}
```
~~~

The bot will generate and upload `milestones_gantt.png` in that channel.
