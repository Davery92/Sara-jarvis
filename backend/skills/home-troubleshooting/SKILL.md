---
name: home-troubleshooting
description: Systematic approach to diagnosing and fixing smart home issues
contexts: [home]
enabled: true
priority: 8
requires:
  env: []
  config: []
user_invocable: false
---

# Home Troubleshooting

## Context
David has a Home Assistant setup with various smart devices. When things aren't working, help diagnose systematically.

## Troubleshooting Approach

### 1. Clarify the Problem
- What's the expected behavior?
- What's actually happening?
- When did it start? (Recent change?)
- Affecting one device or multiple?

### 2. Check the Basics First
Before diving deep:
- Is the device powered?
- Is it reachable on the network?
- Has anything changed recently? (Updates, new devices, network changes)

### 3. Use Available Tools
- Use `home_assistant_state` to check device states
- Use `home_assistant_control` to test commands
- Check if automation is the issue vs. device itself

### 4. Common Issues

**"Light won't turn on"**
1. Check if device shows as unavailable in HA
2. Try power cycling the device
3. Check if it responds to physical control
4. Check Zigbee/Z-Wave mesh status if applicable

**"Automation isn't running"**
1. Is automation enabled?
2. Check trigger conditions - are they being met?
3. Check conditions - are they blocking execution?
4. Look at automation trace/history

**"Device shows wrong state"**
1. Polling vs. push updates?
2. Try forcing a state refresh
3. Check integration logs

## Communication Style
- Start simple, escalate complexity as needed
- Explain why we're checking each thing
- If unsure, say so and suggest resources

## What NOT To Do
- Don't suggest factory reset as first option
- Don't assume David hasn't checked the obvious (but do confirm)
- Don't make network changes without explicit approval
