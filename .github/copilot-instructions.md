# Execution & Anti-Loop Rules

- **No Narration Loops:** Never narrate intentions repeatedly (e.g., "Let me run", "Let me check", "Let me go"). Either invoke a tool immediately or output the final answer.
- **Single-Pass Verification:** Run a verification command or test at most once per change. If the output shows no new errors or confirms completion, stop immediately and summarize the result.
- **Circuit Breaker:** If you execute the same tool or check twice with no workspace changes or new information, stop calling tools and ask the user how to proceed.
- **Concise Reasoning:** Keep internal reasoning brief and linear. Do not second-guess completed steps.

# Terminal & Tool Usage Rules

When executing terminal commands or fetching external data, follow these rules strictly:

1. **One command per tool call:** Do not chain unrelated commands together using `;` or `&&`. Run each logical step in its own separate terminal tool call.
2. **No decorative `echo` banners:** Do not use `echo "=== ... ==="` headers inside shell commands; explain what you are doing in your chat response instead.
3. **Avoid `cd /tmp`:** Run read-only commands directly from the current workspace directory unless file creation is strictly required.
4. **Prefer built-in fetch tools over `curl`:** When reading raw files or public JSON/text endpoints (such as `://githubusercontent.com`), use the built-in web/URL fetch tool instead of shelling out to `curl`.
5. **Keep `gh` commands simple:** Use `gh api` with `--jq` for filtering rather than piping output through `grep`, `awk`, or `head`.

## CRITICAL TERMINAL CONSTRAINTS (MUST OBEY)

NEVER combine commands with `&&`, `;`, or `|`. Every shell execution MUST be a single standalone binary call.

- BAD: `echo "=== status ===" && git status && git branch`
- GOOD: Call terminal tool with `git status`, wait for result, then call terminal tool with `git branch`.
  NEVER use `echo` to print section headers.
