# Friction log

Project: Drawer. Builder: triixdev. All dates are Oct 22 and 23, 2026 (IST).

## 1. The MCP Python SDK 2.x changed the import most examples use
- Task: start an MCP server in Python.
- Steps: I installed mcp 2.3.0 and used `from mcp.server.fastmcp import FastMCP` like most examples do.
- Expected: it imports.
- Actual: ModuleNotFoundError. The message said FastMCP is now called MCPServer in 2.x and linked a migration guide.
- Severity: low.
- Workaround: I switched to `mcp.server.mcpserver.MCPServer`.
- Suggestion: update the quickstarts or keep an alias for a release.

## 2. Bedrock was blocked on my new free plan account
- Task: call Amazon Nova Micro from the playground and from the Converse API.
- Steps: I opened the model in the catalog and sent "hello" in the playground. Then I called Converse with a Bedrock API key in ap-south-1 and us-east-1 using the inference profile IDs.
- Expected: a reply.
- Actual: first an AccessDeniedException saying my account was being verified and that this takes under 2 hours. Later a ValidationException ("Operation not allowed") in both regions and in the playground. The Anthropic use case form said I wasn't authorized. I opened a support case. About 10 hours later AWS replied that my account had no verification restrictions and passed the case to Billing and Accounts. On the morning of Oct 23 the same error was still there.
- Severity: high. It blocked the AWS Builder challenge for me.
- Workaround: none that I found in time. Drawer's optional AI step falls back to a plain template.
- Suggestion: give one error message that names the real cause. Show on the billing page which services a free plan restricts. Make the console message and support agree about the account.

## 3. The model page shows a model ID but the model needs an inference profile
- Task: find the ID to use for Nova Micro.
- Steps: I copied the Model ID from the model page.
- Expected: that ID works.
- Actual: the page says the model can only be used through an inference profile but doesn't show the profile ID. I found it under Infer and then Cross-region inference.
- Severity: medium.
- Workaround: I looked up the apac profile in the other menu.
- Suggestion: show the profile IDs for the selected region next to the model ID.

## 4. The support email address in the console message doesn't accept mail
- Task: contact AWS about the verification message.
- Steps: the console message told me to write to aws-verification@amazon.com so I did.
- Expected: a person reads it.
- Actual: three hours later I got an automatic reply from a no-reply address that pointed me to a web form.
- Severity: medium. It cost me about three hours.
- Workaround: I used the web form and then opened a support case.
- Suggestion: put the form link in the console message instead of an address that bounces.

## 5. The hackathon credit instructions contradict each other
- Task: get the AWS credits the rules describe.
- Steps: I read the rules. They describe a $150 credit request form open until Oct 21. Then I read the Oct 7 note saying the credit codes had run out.
- Expected: one clear instruction.
- Actual: both are still on the page.
- Severity: low.
- Workaround: I used the credits that came with my free plan account.
- Suggestion: remove the request form paragraph once the codes are gone.

## Feature requests

- Important: a local test client for Alexa+ account linking and tool calls. Without an Alexa+ account I had to write the OAuth and PKCE flow by hand to test.
- Important: show inference profile IDs and free plan limits on each Bedrock model page.
- Nice to have: docs on returning cards or MCP Apps for screen devices with a simulator.
