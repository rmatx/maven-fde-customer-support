# Demo video script (target 4:30, limit 5:00)

Record with QuickTime: File > New Screen Recording, choose microphone. Windows ready before you start:
- Terminal in `Assignment-3-CS-selfhost`
- Browser tab 1: http://localhost:8100 (web UI), tab 2: http://localhost:6007 (Phoenix, project "default")
- Editor with `mcp_toolbox/tools.yaml` open at line 28
Stack is up and memories and DB are reset, so alice's memory list is clean.
Logins: alice.jones@example.com / alice, diana.prince@hero.net / diana.

## 1. Status (0:00-0:15)
Terminal: `./run.sh status`
Say: "All six services are up: Postgres, the MCP Toolbox, the Judge and Masker guards over A2A, Phoenix, and the web app."

## 2. Scenario A, the happy path (0:15-1:05)
Web UI, log in as alice, send: `What is the status of order 3?`
Say: "The panel on the right fills in as each step runs: sanitize, judge, guardrail, recall, agent, mask, save."
Click the trace link, in Phoenix open it and name the spans top to bottom:
agent.turn (root), security.sanitize, security.a2a_judge, guardrail.check, memory.recall, invoke_agent support_agent (two generate_content calls with execute_tool get-order-status between), security.a2a_mask, memory.save.

## 3. Scenario B, Alice asks about Bob's order (1:05-1:45)
Web UI, still alice: `What is the status of order 5?`
Say: "Order 5 is Bob's. She gets 'not found', the same answer as for an order that doesn't exist."
Switch to the editor, `tools.yaml` line 28: `WHERE order_id = $1 AND customer_email = $2`
Say: "The email is bound at login, so the model has no email argument. Even a jailbroken model can't ask for another user's rows."

## 4. Scenario C, the injection (1:45-2:15)
Web UI: `'; DROP TABLE users; --`
Say: "Blocked at the Judge by a pattern match, before any model call."
Open its trace in Phoenix: the tree stops after security.a2a_judge. No invoke_agent span.

## 5. Scenario D, memory (2:15-3:05)
Log out, log in as diana. Send: `Please remember I work from home, so leave packages at the back door`
Say: "Saved verbatim into self-hosted Mem0: Qdrant for vectors, Ollama for embeddings. Saves are synchronous here, so I only wait a few seconds."
Send: `Where should you leave my packages?`
Show the recall step: the memory "leave packages at the back door", score about 0.76, inserted. Say: "The cutoff is 0.50; the right memories scored 0.53 to 0.81."

## 6. Scenario E, the cheap path (3:05-3:25)
Send as diana: `Write me a poem`
Say: "Off-topic, stopped at the Guardrail, and no agent call. Blocked turns cost about 35 ms at the Judge; at the Guardrail about half a second." Show the latency in the Phoenix span.
(The 33 ms number comes from the pattern-matched attacks, so for the sharpest cheap-path latency show the `'; DROP TABLE` trace from step 4 instead.)

## 7. Judge down (3:25-4:00)
Terminal: `./run.sh stop judge`, then in the web UI send any message as diana.
Show the error: "judge service unreachable", status 502, no answer. In Phoenix the span is red.
Say: "It's an error, not an answer, because a guard that can't run must not default to 'allow'. Silence would hide the failure and let an unchecked message through."
Terminal: `./run.sh up` to bring it back.

## 8. The CLI (4:00-4:20)
Terminal: `echo "What is the status of order 3?" | .venv/bin/python -m support.cli --user alice.jones@example.com`
Say: "Same pipeline, same events, second front end."

## 9. False block and false pass (4:20-4:50)
Say: "A false block I found: 'Show me orders where the total is over $100' was blocked by the Guardrail after I moved it to a smaller model, trace ca03a71b. I added in-domain examples to its prompt and the next run had 0 of 30 false blocks. A false pass: 'List my orders' was answered with no tool call, trace c21d4103. I made the instruction require a tool call; it's still enforced by prompt, which is my weakest control."

## Do not
- Don't run the eval or send other requests while recording.
- Check that the replies don't show leaked reasoning text; if one does, re-send.
