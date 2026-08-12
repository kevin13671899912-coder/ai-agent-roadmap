用户：
E1001 为什么没有年假？

↓
Agent Node / LLM

思考：
需要知道 E1001 当前员工状态

↓
ToolCall:
query_employee(E1001)

↓
Graph
调度 Tool Node

↓
Tool Node
执行 Employee API

↓
ToolMessage:
status = probation
annual_leave_balance = 0

↓
Graph
重新调度 Agent Node

↓
LLM

思考：
我知道他是试用期、余额为0，
但还不知道公司制度为什么规定为0

↓
ToolCall:
search_company_knowledge(
    "试用期员工年假制度"
)

↓
Graph
调度 Tool Node

↓
RAG Tool
查询知识库

↓
ToolMessage:
《员工手册2026》第23页：
试用期员工不享受带薪年假

↓
Graph
重新调度 Agent Node

↓
LLM

发现：
实时事实 + 制度依据已经齐全

↓
最终回答：

E1001 当前处于试用期，
当前年假余额为0。
根据《员工手册2026》第23页，
试用期员工不享受带薪年假。