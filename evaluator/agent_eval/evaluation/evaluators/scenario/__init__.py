"""场景专属评估器（阶段 4）。

各场景自带的评估器模块放在此包下，由对应场景包的 ``manifest.entry_points`` 在加载时
导入并经 ``@registry.register`` 注册，使评估器随场景包可用（解除评估器固定 courseware 一组）。
"""
