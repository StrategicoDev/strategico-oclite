# OCLite Release Notes

## 0.2.14 - 2026-05-11

- Added a runnable GitHub Copilot chat adapter.
- GitHub device-login profiles now exchange for short-lived Copilot session tokens and cache them.
- Copilot aliases can be exposed and assigned to agents from the normal Models workflow.
- Provider/model tests now verify Copilot by listing models through the Copilot API.
- Fixed Copilot OAuth/token import leaving a blank pre-opened browser tab behind.
- OpenAI Codex OAuth now reports when callback port 1455 is already owned by another process instead of silently sending the browser to a stale callback server.
- OAuth callback errors now explain stale/mismatched login attempts more clearly.
- Added a front-end Provider Setup flow so GitHub Copilot can be enabled with the required device-login profile before exposing models.
- Copilot model exposure is now blocked until the Copilot OAuth profile exists.
- Added GitHub Copilot login help for the device-code flow.
- Removed per-alias auth controls from Expose Model; aliases now inherit auth from Provider Setup.
- Removed automatic page polling and added a manual refresh button to the Tasks page.
- Added Load Models in Expose Model to fetch valid model ids from the selected provider.
- Copilot model tests now fail with available model suggestions when the alias model id is not valid.
- Copilot provider readiness now distinguishes a stored token from a validated Copilot session token.
- Switched Copilot setup from PAT-first auth to the GitHub Copilot Plugin device login flow and the `api.individual.githubcopilot.com` runtime host.

## 0.2.12 - 2026-05-11

- Added a GitHub Copilot OAuth/token import route.
- Copilot auth can import `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, or `gh auth token`.
- Added optional GitHub device login support when `OCLITE_GITHUB_OAUTH_CLIENT_ID` is configured.
- Kept Copilot as provider authentication only until a runnable Copilot model adapter is added.

## 0.2.11 - 2026-05-11

- Added Remove actions for exposed model aliases.
- Added backend-safe model alias deletion.
- If agents use a model being removed, OCLite now requires one replacement model and applies it to all affected agents.
- Protected the built-in `mock:echo` model from deletion.

## 0.2.10 - 2026-05-11

- Made Windows start scripts ignore the Microsoft Store Python alias unless it points to a real Python runtime.
- Added automatic detection for repo virtualenv, Codex bundled Python, Python Launcher, python3, and python.
- Updated the Windows startup scheduled task helper to reuse the same Python detection logic.

## 0.2.9 - 2026-05-11

- Added a simple Windows start script for manually launching the gateway without installing startup-on-login.
- Added a `.cmd` wrapper for easier launch from Explorer or Command Prompt.

## 0.2.8 - 2026-05-11

- Made Restart Gateway tolerate the brief network disconnect during process restart and wait for the gateway to come back.
- Added a Windows scheduled-task installer so OCLite can start automatically at login after a PC reboot.
- Clarified that first startup after reboot must be handled by the operating system, not the in-browser restart button.

## 0.2.7 - 2026-05-11

- Added the `/model` runtime command for Telegram and local sessions.
- `/model` reports the current agent, session, model alias, resolved provider/model, and auth state without calling the LLM.
- Runtime slash commands no longer create tracked tasks.

## 0.2.6 - 2026-05-11

- Added per-exposed-model status in the Models list.
- Added a Test button next to each exposed model alias.
- Show OAuth-backed aliases as linked when their OAuth profile exists.
- Added an alias-level model auth test endpoint.

## 0.2.5 - 2026-05-11

- Made the Expose Model form more compact.
- Listed exposed models as dense rows instead of large cards.
- Drove the auth selector from the selected provider's supported auth method.
- Started OAuth automatically from Expose Model when an OAuth-backed provider is selected.

## 0.2.4 - 2026-05-11

- Reduced model setup to only show providers that OCLite can authenticate and run today.
- Hid adapter-pending providers from the normal Expose Model workflow.
- Added backend validation so non-ready providers cannot be exposed by accident.

## 0.2.3 - 2026-05-11

- Limited the OAuth connect dropdown to providers with a real supported OAuth adapter.
- Clarified that direct providers like Copilot are valid catalogue labels but need runnable adapters before active agent use.
- Improved auth diagnostics so direct providers without an adapter report "not testable" instead of false success.

## 0.2.2 - 2026-05-11

- Simplified the Models page into one primary Expose Model workflow.
- Changed provider setup to an alphabetized valid-provider catalogue instead of manual provider entry.
- Added provider validation so new exposed models must use a known provider id.
- Kept OAuth and auth diagnostics available without making providers the main setup step.

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
