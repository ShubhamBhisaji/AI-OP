import sys
sys.path.insert(0, ".")
from ai.ai_adapter import AIAdapter
from memory.memory_manager import MemoryManager
from registry.agent_registry import AgentRegistry
from tools.tool_manager import ToolManager
from skills.skill_engine import SkillEngine
from factory.agent_factory import AgentFactory

ai = AIAdapter.__new__(AIAdapter)
ai.provider = "openai"
ai.model = "gpt-4o"
mem = MemoryManager(persist=False)
reg = AgentRegistry(persist=False)
tm  = ToolManager()
se  = SkillEngine(registry=reg)
fac = AgentFactory(registry=reg, tool_manager=tm, ai_adapter=ai)

fac.create("research_agent")
fac.create("coding_agent")
fac.create("marketing_agent")
fac.create("automation_agent")
fac.create("data_analysis_agent")

upgrade = se.upgrade("research_agent")
se.upgrade("coding_agent")

print("=" * 50)
print("  AetherAi-A Master AI  v1.0.0")
print("  All systems OPERATIONAL")
print("=" * 50)
print()
print("Registered Agents:")
for name in reg.list_names():
    r = se.get_performance_report(name)
    skills = ", ".join(r["skills"]) or "none"
    tools  = ", ".join(r["tools"])  or "none"
    print("  [%s]  role=%s  v%s" % (name, r["role"], r["version"]))
    print("     skills : %s" % skills)
    print("     tools  : %s" % tools)
    print()

print("Upgrade result for research_agent:")
print("  version     :", upgrade["version"])
print("  skills added:", upgrade["skills_added"])
print()
print("Factory presets available:")
for p in AgentFactory.list_presets():
    print("  -", p)
print()
print("Registered tools:", tm.list_tools())
print()
print("Memory snapshot:", mem.snapshot())
