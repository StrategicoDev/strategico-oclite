# OCLite Release Notes

## 0.2.1 - 2026-05-11

- Changed provider setup from a restrictive allowlist to an open provider registry.
- Added direct provider activation suggestions from OpenClaw/Hermes-style model strings.
- Allowed custom providers and custom provider/model combinations to be registered.
- Added model activation autocomplete for common `provider/model` strings.
- Added clearer runtime errors for direct providers that still need an adapter or OpenAI-compatible base URL.

## 0.2.0 - 2026-05-11

- Added app version metadata and release notes in the control UI.
- Added provider presets so supported model providers are easier to select and verify.
- Restructured model setup around providers, provider-linked models, and agent-facing aliases.
- Added SVG logo and favicon assets.
- Improved task dashboard scrolling, task limits, and selected task detail rendering.
- Strengthened orchestration task handoff and delegate result return flow.

## 0.1.0 - 2026-05-06

- Initial lightweight OCLite gateway with Telegram routing, agents, sessions, models, and a minimal control UI.
