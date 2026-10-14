import asyncio
import json
import os
import sys

from dotenv import load_dotenv
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

if not os.getenv("MODEL"):
    raise RuntimeError("Set MODEL in your .env file.")

server = StdioServerParameters(
    command=sys.executable,
    args=["k8s_mcp_server.py"],
)

def convert_tools(mcp_tools):
    """Convert MCP tool schemas to Ollama function tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or tool.name,
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools
    ]

def extract_result(result):
    if result.isError:
        return "MCP tool returned an error."

    return "\n".join(
        item.text
        for item in result.content
        if hasattr(item, "text")
    )

async def main():
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            MODEL = os.getenv("MODEL")
            discovered = await session.list_tools()
            tools = convert_tools(discovered.tools)

            print(f"Kubernetes agent running with {MODEL}")
            print("Tools:", [t.name for t in discovered.tools])

            while True:
                question = input("\nYou: ").strip()

                if question.lower() in ("exit", "quit"):
                    break
                if not question:
                    continue

                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a Kubernetes troubleshooting assistant. "
                            "Use tools to verify facts before diagnosing. "
                            "Never invent logs or cluster results. "
                            "Only use read-only tools. Explain findings "
                            "and recommend safe next steps."
                        ),
                    },
                    {"role": "user", "content": question},
                ]

                for _ in range(6):
                    response = await asyncio.to_thread(
                        ollama.chat,
                        model=MODEL,
                        messages=messages,
                        tools=tools,
                    )

                    message = response.message
                    messages.append(message)

                    if not message.tool_calls:
                        print("\nAgent:", message.content)
                        break

                    for tool_call in message.tool_calls:
                        name = tool_call.function.name
                        args = tool_call.function.arguments

                        # Ollama may return arguments as a dictionary.
                        if not isinstance(args, dict):
                            args = json.loads(args)

                        print(f"Calling MCP tool: {name}")

                        try:
                            result = await asyncio.wait_for(
                                session.call_tool(name, args),
                                timeout=20,
                            )
                            output = extract_result(result)
                        except asyncio.TimeoutError:
                            output = "Tool timed out; diagnosis is unconfirmed."
                        except Exception as exc:
                            output = (
                                f"Tool call failed: {type(exc).__name__}"
                            )

                        messages.append({
                            "role": "tool",
                            "tool_name": name,
                            "content": output[:12000],
                        })
                else:
                    print("Stopped: maximum tool-call rounds reached.")


if __name__ == "__main__":
    asyncio.run(main())