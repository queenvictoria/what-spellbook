# What spellbook?

This project is designed to recommend spells to suit a scenario or encounter given a prompt and grounded in a ruleset and spell list.

The first proof-of-concept is for a D&D 5.5e (2024) Celestial Warlock with Pact of the Tome. Pact of the Tome enables rewriting of the spell-book after a short or long rest. And the class combo means spells can be selected from _any class_ if it has the [xxxx?] tag.

Given markdown (or similar) formatted spell lists, a character's level, and any other relevant information, and provided with a prompt (a scenario or encounter) it will recommend the cantrips and spells the new spellbook should contain, a rationale, and a cheatsheet of how to deploy them (possibly in combination with other prepared spells).

This project will store all settings in localstorage exportable to JSON and the cloud. The prompt and scenario history will be stored along with a rating from the player as to how well the recommendation performed (including an updated scenario or encounter prompt).

It will run as a webapp optimised for mobile. The interface should be minimal: character selection and storage, a history of scenarios, an editor for the character.

## Sources

5.5e SRD has 339 spells. DNDBeyond 400+ (includes legacy and trademarked spells).

https://github.com/downfallx/dnd-5e-srd-markdown/blob/master/spells.md
https://drive.google.com/drive/folders/16T2y1UaSgLQtEBWXmSU3zc0L7L6TKVT8
https://5e24srd.com/spells/spell-descriptions.html
https://toolsandtaverns.com/spells


## Versions

### Front end

Framework: React + Vite
Status: not started. Planned in ARCHITECTURE and ROADMAP


### Backend

None as yet

### CLI

Framework: Python and langchain
Status: Testing in main.py

- [x] Switch to /slash+TAB style commands like Claude CLI and Discord
- Add /test command
- Add /help command
- Move character/s to JSON/YAML file in `data/characters`
- Move remaining config to .env file

LLM backend: OpenRouter (`deepseek/deepseek-v4.1-flash-1017`) via `OPENROUTER_API_KEY` in a gitignored `.env`, falling back to local Ollama (`qwen3.5:4b`) when no key is present.
