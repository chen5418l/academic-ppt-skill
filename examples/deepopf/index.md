# DeepOPF完整专题案例

主题：数据驱动的电力系统最优潮流。案例呈现数据科学与电力运行优化的交叉，使用公开论文进行方法解释与结果分析，不代表原文实验已复现或实际电网已部署。

- [20页PPT](deepopf-academic-v3.pptx)
- [实际页面与证据清单](evidence.json)
- [总体研究架构预览](previews/slide-07.png)
- [实验数据路线预览](previews/slide-12.png)
- [原文加速结果预览](previews/slide-15.png)
- [可行率结果预览](previews/slide-16.png)
- [惩罚权重结果预览](previews/slide-17.png)

各页预览按 `slide-01.png` 至 `slide-20.png` 编号，页序见清单。第7、9、12、19页采用原创复杂科研图片；图片内的文字和结构只能整体编辑。其余技术图、页面标题、结论、表格与数据图采用原生PPT对象。没有复制用户截图、作者原图或论文全文。

复杂图的设计说明和生成约束见 [科研图说明](figures/notes.md)。图片中的科学内容已按原文逐项核对，生成图仍不能作为实验数据。实际的原文数值保存在第15–17页的原生图表中。

## 研究主线

1–4页建立问题与最优潮流基础；5–11页解释学习、物理重构和约束处理；12–14页说明数据、实验设计和评价口径；15–17页呈现Tables IV–VI的报告结果；18–20页限定结论并提出待验证研究方向。

主要论文采用 [DeepOPF AC-OPF v6](https://arxiv.org/abs/2007.01002v6)，不是早期2020版本。相关方法参考 [DeepOPF+](https://arxiv.org/abs/2009.03147) 与 [DeepOPF-V](https://arxiv.org/abs/2103.11793)。稳态基础参见 [MATPOWER User Manual](https://matpower.org/docs/MATPOWER-manual.pdf) §4、§6。

## 保留的科学边界

- 网页摘要写成本差异 `<0.1%`，v6 PDF摘要写 `<0.2%`；结果按具体表格与负荷条件报告。
- Table IV恢复前可行率与恢复后可行率分别说明；测试达到100%不能推广为全域保证。
- Table VI中 `<0.1%` 保留为范围，没有画成精确点值。
- 12,500样本与80/20来自原文，训练10,000、测试2,500由比例计算。
- 2000母线算例属于合成系统，不标称IEEE标准2000母线。
- Table II与实现节对参考角的表述需核对，本页区分已知设定与网络预测。
- 没有额外生成原文未给出的误差条、显著性、训练曲线或部署记录。

可以用 `python scripts/audit_deck.py examples/deepopf/deepopf-academic-v3.pptx examples/deepopf/evidence.json` 核对实际页面、来源关联、表格和图表绑定。检查能力的适用边界见 [证据与连续修改](../../references/evidence-and-revisions.md)。
