# Discord Server Setup Runbook (Automated)

This runbook bootstraps the Luvatrix server structure defined in `ops/discord/discord.md` using:
- `ops/discord/ops/blueprint.json`
- `ops/discord/scripts/bootstrap_discord.py`

## 1) One-Time Manual Prerequisites

1. Create a new Discord server (or choose an existing one).
2. In the Discord Developer Portal, create a **Team** first (for example `Luvatrix Platform`).
3. Create your Discord application under the Team owner (not a personal owner).
4. Add a bot user to that application.
5. Invite at least one backup admin/lead to the Team.
6. Assign least-privilege Team roles (only 1-2 owners/admins).
7. Ensure policy: no production bot app is individually owned.
8. Invite the bot to your server with permissions to:
- Manage Roles
- Manage Channels
- Send Messages
- Manage Messages (for pinning)
- Read Message History
9. Copy:
- Bot token
- Guild (server) ID (Developer Mode required)

## 2) Dry Run (No Changes)

```bash
cd /Users/aleccandidato/Projects/luvatrix
export DISCORD_BOT_TOKEN='YOUR_BOT_TOKEN'
export DISCORD_GUILD_ID='YOUR_GUILD_ID'
python ops/discord/scripts/bootstrap_discord.py
```

## 3) Apply Server Bootstrap

```bash
cd /Users/aleccandidato/Projects/luvatrix
export DISCORD_BOT_TOKEN='YOUR_BOT_TOKEN'
export DISCORD_GUILD_ID='YOUR_GUILD_ID'
python ops/discord/scripts/bootstrap_discord.py --apply
```

If you renamed categories/channels and need to remove old legacy layout entries:

```bash
cd /Users/aleccandidato/Projects/luvatrix
export DISCORD_BOT_TOKEN='YOUR_BOT_TOKEN'
export DISCORD_GUILD_ID='YOUR_GUILD_ID'
python ops/discord/scripts/bootstrap_discord.py --prune-legacy
python ops/discord/scripts/bootstrap_discord.py --apply --prune-legacy
```

Notes:
1. First command is a dry-run delete preview.
2. Second command applies deletion for legacy categories/channels listed in `ops/discord/ops/blueprint.json` under `legacy_cleanup`.

What this automates:
1. Creates required roles from `ops/discord/discord.md`.
2. Creates all categories/channels from `ops/discord/discord.md`.
3. Applies onboarding-gate visibility (`Onboarded` role required for most categories).
4. Applies restricted visibility for `06_EXECUTIVE` (CEO + Leads only).
5. Applies read-only feed channels where configured (for bot-driven updates).
6. Posts and pins starter messages/templates in key channels.

## 4) Install Recommended Non-LLM Bots

Add these from their official pages:
1. Carl-bot: moderation/roles/hygiene.
2. sesh (optional n8n later): scheduling/workflow cadence.
3. MyRepoBot: GitHub/release activity routing.
4. Ticket Tool: incident and risk ticket operations.

## 5) Configure AI Identity Bots (Single LLM Backend)

Create role-scoped identities in your custom bot:
1. `AI-Architect`
2. `AI-Implementer`
3. `AI-Test-Engineer`
4. `AI-Release-Reviewer`

Each identity should have:
- allowed channel list
- allowed command list
- escalation rules
- immutable logging

## 6) Post-Bootstrap Manual Checklist (5-10 mins)

1. Assign yourself `CEO` and your leads `Leads`.
2. Keep new users/agents without `Onboarded` until checklist is complete.
3. After onboarding completion, assign role `Onboarded` to unlock non-onboarding categories.
4. Verify AI policy: AI agents cannot create private channels.
5. Verify active milestone workspace categories exist and follow channel template.
6. Paste current non-private artifacts into:
- `#project-charter-public`
- `#workplan-public`
- `#reports-index-public`
7. Confirm `#onboarding-checklist` and `#agent-onboarding` are pinned.
8. Confirm `06_EXECUTIVE` is hidden from non-lead roles.
9. Confirm `#milestones-gantt` and `#agile-board-feed` are read-only.
10. Run one onboarding simulation with a new member or AI agent.

## 6.1) Automated Rollout Verification

Run this after bot installs and bootstrap:

```bash
cd /Users/aleccandidato/Projects/luvatrix
export DISCORD_BOT_TOKEN='YOUR_BOT_TOKEN'
export DISCORD_GUILD_ID='YOUR_GUILD_ID'
./ops/discord/scripts/check_discord_bot_rollout.sh
```

What it checks:
1. Bot token can reach the target guild.
2. Bot members currently installed in the server.
3. Presence of expected non-LLM bots (`Carl-bot`, `sesh`, `MyRepoBot`, `Ticket Tool`) and `Luvatrix Ops Bot`.
4. Presence of critical channels needed for operations.

## 7) Access Governance Checklist (Monthly)

1. Review Team membership and remove stale users.
2. Confirm only designated leaders hold Team owner/admin roles.
3. Rotate bot tokens if compromise is suspected or staffing changed.
4. Audit bot permissions in server and remove unused privileged scopes.
5. Verify `06_EXECUTIVE` visibility is still restricted to `CEO` and `Leads`.
6. Confirm all bot actions that impact decisions are logged to governance channels.
7. Record review date, reviewer, and actions taken in `#planning-change-log` or ops notes.

## Notes

1. Script is idempotent for structure creation and safe to rerun.
2. Keep token in environment variables only; never commit secrets.
3. Update `ops/discord/ops/blueprint.json` when server structure evolves.
