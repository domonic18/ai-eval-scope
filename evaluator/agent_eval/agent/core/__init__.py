"""Agent 共享内核：工具基座、预算、会话日志、回调、模型桥接与会话状态。

被执行域（executor）与工作台域（workbench）共同依赖；本包导入零额外依赖，
heavyweight 依赖（langchain/langgraph）在各模块内惰性导入。
"""
