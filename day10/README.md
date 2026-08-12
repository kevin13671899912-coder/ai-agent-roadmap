# Day 10：Human-in-the-loop

## 核心流程

- 使用 interrupt() 暂停工作流
- 使用 Checkpointer 保存执行现场
- 使用相同 thread_id 找回流程
- 使用 Command(resume=...) 提交人工输入
- 根据审批结果进入不同分支

## 测试场景

1. 经理批准 → HR 处理 → completed
2. 经理拒绝 → rejected → END

## 今日结论

暂停的是 Workflow，不是线程。