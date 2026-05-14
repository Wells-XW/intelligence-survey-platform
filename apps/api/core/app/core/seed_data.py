"""Seed data: pre-populate the knowledge_scales and knowledge_entries tables.

Called from the application lifespan (main.py) when tables are first created.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.knowledge_entry import KnowledgeEntry
from ..models.knowledge_scale import KnowledgeScale

SCALES_SEED: list[dict] = [
    {
        "name": "Rosenberg 自尊量表 (RSES)",
        "discipline": "psychology",
        "description": "Rosenberg Self-Esteem Scale — 最广泛使用的自尊测量工具，10 题，4 点 Likert。",
        "items": [
            {"code": "RSE01", "text": "总体而言，我对自己感到满意", "reverse_scored": False},
            {"code": "RSE02", "text": "有时我觉得自己一无是处", "reverse_scored": True},
            {"code": "RSE03", "text": "我觉得自己有很多优点", "reverse_scored": False},
            {"code": "RSE04", "text": "我能够像大多数人一样把事情做好", "reverse_scored": False},
            {"code": "RSE05", "text": "我觉得自己没有什么值得骄傲的", "reverse_scored": True},
            {"code": "RSE06", "text": "我有时确实感到自己很无用", "reverse_scored": True},
            {"code": "RSE07", "text": "我认为自己是一个有价值的人，至少与别人不相上下", "reverse_scored": False},
            {"code": "RSE08", "text": "我希望我能更尊重自己", "reverse_scored": True},
            {"code": "RSE09", "text": "总的来说，我倾向于认为自己是一个失败者", "reverse_scored": True},
            {"code": "RSE10", "text": "我对自己持有积极态度", "reverse_scored": False},
        ],
        "cronbach_alpha": 0.88,
        "cronbach_alpha_history": [
            {"value": 0.88, "sample_n": 5024, "year": 1989, "citation": "Rosenberg, M. (1989). Society and the adolescent self-image. Revised edition."},
            {"value": 0.87, "sample_n": 1562, "year": 2015, "citation": "Sinclair et al. (2015). Psychometric properties of the RSES."},
        ],
        "citations": [
            {"title": "Society and the adolescent self-image (Revised edition)", "authors": "Rosenberg, M.", "year": 1989, "doi": "10.1515/9781400876136"},
        ],
        "language": "zh",
    },
    {
        "name": "生活满意度量表 (SWLS)",
        "discipline": "psychology",
        "description": "Satisfaction With Life Scale — 5 题，7 点 Likert，评估整体生活满意度。",
        "items": [
            {"code": "SW01", "text": "在大多数方面，我的生活接近我的理想", "reverse_scored": False},
            {"code": "SW02", "text": "我的生活条件非常好", "reverse_scored": False},
            {"code": "SW03", "text": "我对我的生活感到满意", "reverse_scored": False},
            {"code": "SW04", "text": "到目前为止，我已经得到了我在生活中想要的重要东西", "reverse_scored": False},
            {"code": "SW05", "text": "如果我能重新活一次，我几乎不会做任何改变", "reverse_scored": False},
        ],
        "cronbach_alpha": 0.87,
        "cronbach_alpha_history": [
            {"value": 0.87, "sample_n": 176, "year": 1985, "citation": "Diener, E., Emmons, R. A., Larsen, R. J., & Griffin, S. (1985). The Satisfaction With Life Scale. JPA, 49(1), 71-75."},
            {"value": 0.83, "sample_n": 1537, "year": 2018, "citation": "Emerson et al. (2018). A systematic review of SWLS psychometrics."},
        ],
        "citations": [
            {"title": "The Satisfaction With Life Scale", "authors": "Diener, E., Emmons, R. A., Larsen, R. J., & Griffin, S.", "year": 1985, "doi": "10.1207/s15327752jpa4901_13"},
        ],
        "language": "zh",
    },
    {
        "name": "系统可用性量表 (SUS)",
        "discipline": "management",
        "description": "System Usability Scale — 10 题，5 点 Likert，广泛用于评估系统/产品可用性。",
        "items": [
            {"code": "SU01", "text": "我认为我会愿意经常使用这个系统", "reverse_scored": False},
            {"code": "SU02", "text": "我发现这个系统过于复杂", "reverse_scored": True},
            {"code": "SU03", "text": "我认为这个系统容易使用", "reverse_scored": False},
            {"code": "SU04", "text": "我认为我需要技术人员的支持才能使用这个系统", "reverse_scored": True},
            {"code": "SU05", "text": "我发现系统中的不同功能被很好地整合在一起", "reverse_scored": False},
            {"code": "SU06", "text": "我认为这个系统存在太多不一致", "reverse_scored": True},
            {"code": "SU07", "text": "我认为大多数人很快就能学会使用这个系统", "reverse_scored": False},
            {"code": "SU08", "text": "我发现这个系统使用起来很笨拙", "reverse_scored": True},
            {"code": "SU09", "text": "在使用这个系统时我感到非常自信", "reverse_scored": False},
            {"code": "SU10", "text": "在使用这个系统之前我需要学习很多东西", "reverse_scored": True},
        ],
        "cronbach_alpha": 0.91,
        "cronbach_alpha_history": [
            {"value": 0.91, "sample_n": 275, "year": 1996, "citation": "Brooke, J. (1996). SUS: A quick and dirty usability scale."},
        ],
        "citations": [
            {"title": "SUS: A quick and dirty usability scale", "authors": "Brooke, J.", "year": 1996, "doi": "10.1201/9781498710411"},
        ],
        "language": "zh",
    },
    {
        "name": "技术接受模型 (TAM)",
        "discipline": "management",
        "description": "Technology Acceptance Model — 12 题，7 点 Likert，测量感知有用性和感知易用性。",
        "items": [
            {"code": "TA01", "text": "使用该系统能提高我的工作绩效", "reverse_scored": False},
            {"code": "TA02", "text": "使用该系统能提高我的工作效率", "reverse_scored": False},
            {"code": "TA03", "text": "使用该系统能使我更有效地完成工作", "reverse_scored": False},
            {"code": "TA04", "text": "我发现该系统对我的工作有用", "reverse_scored": False},
            {"code": "TA05", "text": "学习操作该系统对我来说很容易", "reverse_scored": False},
            {"code": "TA06", "text": "我发现让系统做我想做的事很容易", "reverse_scored": False},
            {"code": "TA07", "text": "我与系统的交互是清晰且可理解的", "reverse_scored": False},
            {"code": "TA08", "text": "我发现系统使用起来很灵活", "reverse_scored": False},
            {"code": "TA09", "text": "对我来说熟练使用系统很容易", "reverse_scored": False},
            {"code": "TA10", "text": "我发现系统使用起来很简单", "reverse_scored": False},
            {"code": "TA11", "text": "我计划在未来继续使用该系统", "reverse_scored": False},
            {"code": "TA12", "text": "我会推荐他人使用该系统", "reverse_scored": False},
        ],
        "cronbach_alpha": 0.89,
        "cronbach_alpha_history": [
            {"value": 0.89, "sample_n": 112, "year": 1989, "citation": "Davis, F. D. (1989). Perceived usefulness, perceived ease of use, and user acceptance. MIS Quarterly, 13(3), 319-340."},
        ],
        "citations": [
            {"title": "Perceived usefulness, perceived ease of use, and user acceptance of information technology", "authors": "Davis, F. D.", "year": 1989, "doi": "10.2307/249008"},
        ],
        "language": "zh",
    },
    {
        "name": "学术动机量表 (AMS)",
        "discipline": "education",
        "description": "Academic Motivation Scale — 28 题，7 点 Likert，基于自我决定理论测量学术动机类型。",
        "items": [
            {"code": "AM01", "text": "因为有了高中文凭我才能找到高薪工作", "reverse_scored": False},
            {"code": "AM02", "text": "因为我体验到了在学习新知识时的快乐和满足感", "reverse_scored": False},
            {"code": "AM03", "text": "因为我认为大学教育能帮助我更好地为我选择的职业做准备", "reverse_scored": False},
            {"code": "AM04", "text": "因为我喜欢参与与老师的深入讨论", "reverse_scored": False},
            {"code": "AM05", "text": "说实话我不知道，我真的觉得我在学校是在浪费时间", "reverse_scored": True},
            {"code": "AM06", "text": "为了向自己证明我能完成大学学业", "reverse_scored": False},
            {"code": "AM07", "text": "为了证明自己是一个聪明的人", "reverse_scored": False},
            {"code": "AM08", "text": "为了以后有一个体面的生活", "reverse_scored": False},
        ],
        "cronbach_alpha": 0.85,
        "cronbach_alpha_history": [
            {"value": 0.85, "sample_n": 745, "year": 1992, "citation": "Vallerand, R. J., et al. (1992). The Academic Motivation Scale. Educational and Psychological Measurement, 52(4), 1003-1017."},
        ],
        "citations": [
            {"title": "The Academic Motivation Scale: A measure of intrinsic, extrinsic, and amotivation in education", "authors": "Vallerand, R. J., Pelletier, L. G., Blais, M. R., et al.", "year": 1992, "doi": "10.1177/0013164492052004025"},
        ],
        "language": "zh",
    },
    {
        "name": "社会期望性量表 (MCSDS-简版)",
        "discipline": "sociology",
        "description": "Marlowe-Crowne Social Desirability Scale 简版 — 13 题，测量社会期望性反应偏差。",
        "items": [
            {"code": "MC01", "text": "当我犯了错误，我总是愿意承认", "reverse_scored": True},
            {"code": "MC02", "text": "我总是说到做到", "reverse_scored": True},
            {"code": "MC03", "text": "我从来没有特别讨厌过任何人", "reverse_scored": True},
            {"code": "MC04", "text": "曾经有几次我利用过别人", "reverse_scored": False},
            {"code": "MC05", "text": "我有时会因为我得不到的东西而抱怨", "reverse_scored": False},
            {"code": "MC06", "text": "我总是愿意承认自己的无知", "reverse_scored": True},
            {"code": "MC07", "text": "即便对难以相处的人，我也总是以礼相待", "reverse_scored": True},
            {"code": "MC08", "text": "曾经有几次，我嫉妒过别人的好运", "reverse_scored": False},
            {"code": "MC09", "text": "我有时对找借口的人感到恼火", "reverse_scored": False},
            {"code": "MC10", "text": "我从不介意别人从我的错误中吸取教训", "reverse_scored": True},
            {"code": "MC11", "text": "有时我宁愿以牙还牙，而不是原谅和遗忘", "reverse_scored": False},
            {"code": "MC12", "text": "当我不了解某事时，我从不介意承认", "reverse_scored": True},
            {"code": "MC13", "text": "我总是很专注于当下", "reverse_scored": True},
        ],
        "cronbach_alpha": 0.76,
        "cronbach_alpha_history": [
            {"value": 0.76, "sample_n": 623, "year": 1960, "citation": "Crowne, D. P., & Marlowe, D. (1960). A new scale of social desirability. JCCP, 24(4), 349-354."},
        ],
        "citations": [
            {"title": "A new scale of social desirability independent of psychopathology", "authors": "Crowne, D. P., & Marlowe, D.", "year": 1960, "doi": "10.1037/h0047358"},
        ],
        "language": "zh",
    },
    {
        "name": "UCLA 孤独感量表 (第3版)",
        "discipline": "sociology",
        "description": "UCLA Loneliness Scale Version 3 — 20 题，4 点 Likert，测量主观孤独感和社会隔离。",
        "items": [
            {"code": "UL01", "text": "你感到与周围人相处融洽的频率是？", "reverse_scored": True},
            {"code": "UL02", "text": "你感到缺乏陪伴的频率是？", "reverse_scored": False},
            {"code": "UL03", "text": "你觉得没有可以求助的人的频率是？", "reverse_scored": False},
            {"code": "UL04", "text": "你感到孤独的频率是？", "reverse_scored": False},
            {"code": "UL05", "text": "你感到自己是朋友圈一部分的频率是？", "reverse_scored": True},
            {"code": "UL06", "text": "你感到与周围人有许多共同点的频率是？", "reverse_scored": True},
            {"code": "UL07", "text": "你感到不再亲近任何人的频率是？", "reverse_scored": False},
            {"code": "UL08", "text": "你觉得你的兴趣和想法不被周围人分享的频率是？", "reverse_scored": False},
            {"code": "UL09", "text": "你感到自己外向且友善的频率是？", "reverse_scored": True},
            {"code": "UL10", "text": "你感到与别人亲近的频率是？", "reverse_scored": True},
        ],
        "cronbach_alpha": 0.94,
        "cronbach_alpha_history": [
            {"value": 0.94, "sample_n": 487, "year": 1996, "citation": "Russell, D. W. (1996). UCLA Loneliness Scale (Version 3). JPA, 66(1), 20-40."},
        ],
        "citations": [
            {"title": "UCLA Loneliness Scale (Version 3): Reliability, validity, and factor structure", "authors": "Russell, D. W.", "year": 1996, "doi": "10.1207/s15327752jpa6601_2"},
        ],
        "language": "zh",
    },
    {
        "name": "工作倦怠量表 (MBI-GS)",
        "discipline": "health",
        "description": "Maslach Burnout Inventory — General Survey，16 题，7 点频率量表，测量职业倦怠三个维度。",
        "items": [
            {"code": "MB01", "text": "工作让我感到情绪枯竭", "reverse_scored": False},
            {"code": "MB02", "text": "下班时，我感到精疲力竭", "reverse_scored": False},
            {"code": "MB03", "text": "早上起床想到要面对一天的工作，我感到疲倦", "reverse_scored": False},
            {"code": "MB04", "text": "整天工作对我来说确实压力很大", "reverse_scored": False},
            {"code": "MB05", "text": "我能有效地解决工作中出现的问题", "reverse_scored": True},
            {"code": "MB06", "text": "我觉得我在为组织做有用的贡献", "reverse_scored": True},
            {"code": "MB07", "text": "在我看来，我擅长自己的工作", "reverse_scored": True},
            {"code": "MB08", "text": "当我完成工作中的一些事情时，我感到高兴", "reverse_scored": True},
        ],
        "cronbach_alpha": 0.89,
        "cronbach_alpha_history": [
            {"value": 0.89, "sample_n": 10334, "year": 2001, "citation": "Schaufeli, W. B., Leiter, M. P., Maslach, C., & Jackson, S. E. (2001). MBI-GS manual."},
        ],
        "citations": [
            {"title": "Maslach Burnout Inventory — General Survey Manual", "authors": "Schaufeli, W. B., Leiter, M. P., Maslach, C., & Jackson, S. E.", "year": 2001, "doi": ""},
        ],
        "language": "zh",
    },
    {
        "name": "认知需求量表 (NFC-简版)",
        "discipline": "psychology",
        "description": "Need for Cognition Scale 简版 — 18 题，5 点 Likert，测量个体从事和享受认知活动的倾向。",
        "items": [
            {"code": "NF01", "text": "我更喜欢复杂而非简单的问题", "reverse_scored": False},
            {"code": "NF02", "text": "我喜欢负责处理需要大量思考的情况", "reverse_scored": False},
            {"code": "NF03", "text": "思考不是我的乐趣", "reverse_scored": True},
            {"code": "NF04", "text": "我宁愿做不需要太多思考的事情，也不愿做挑战我思维能力的事情", "reverse_scored": True},
            {"code": "NF05", "text": "在长时间艰苦思考之前，我会尽量避免", "reverse_scored": True},
            {"code": "NF06", "text": "我能从长时间深入思考中获得满足感", "reverse_scored": False},
            {"code": "NF07", "text": "我只在必要时才思考", "reverse_scored": True},
            {"code": "NF08", "text": "我更喜欢思考小的日常项目而非长期的项目", "reverse_scored": True},
        ],
        "cronbach_alpha": 0.86,
        "cronbach_alpha_history": [
            {"value": 0.86, "sample_n": 352, "year": 1984, "citation": "Cacioppo, J. T., Petty, R. E., & Kao, C. F. (1984). The efficient assessment of need for cognition. JPA, 48(3), 306-307."},
        ],
        "citations": [
            {"title": "The efficient assessment of need for cognition", "authors": "Cacioppo, J. T., Petty, R. E., & Kao, C. F.", "year": 1984, "doi": "10.1207/s15327752jpa4803_13"},
        ],
        "language": "zh",
    },
    {
        "name": "自我效能感量表 (GSES)",
        "discipline": "psychology",
        "description": "General Self-Efficacy Scale — 10 题，4 点 Likert，测量一般自我效能感。",
        "items": [
            {"code": "SE01", "text": "如果我尽力去做，我总是能够解决难题", "reverse_scored": False},
            {"code": "SE02", "text": "即使别人反对我，我仍有办法取得我所要的", "reverse_scored": False},
            {"code": "SE03", "text": "对我来说，坚持理想和达成目标是轻而易举的", "reverse_scored": False},
            {"code": "SE04", "text": "我自信能有效地应付任何突如其来的事情", "reverse_scored": False},
            {"code": "SE05", "text": "以我的才智，我定能应付意料之外的情况", "reverse_scored": False},
            {"code": "SE06", "text": "如果我付出必要的努力，我一定能解决大多数的难题", "reverse_scored": False},
            {"code": "SE07", "text": "我能冷静地面对困难，因为我信赖自己处理问题的能力", "reverse_scored": False},
            {"code": "SE08", "text": "面对一个难题时，我通常能找到几个解决方法", "reverse_scored": False},
            {"code": "SE09", "text": "有麻烦的时候，我通常能想到一些应付的方法", "reverse_scored": False},
            {"code": "SE10", "text": "无论什么事情在我身上发生，我都能应付自如", "reverse_scored": False},
        ],
        "cronbach_alpha": 0.88,
        "cronbach_alpha_history": [
            {"value": 0.88, "sample_n": 1660, "year": 1979, "citation": "Schwarzer, R., & Jerusalem, M. (1995). Generalized Self-Efficacy Scale."},
            {"value": 0.87, "sample_n": 458, "year": 2001, "citation": "Scholz, U., et al. (2001). Is the GSES a unidimensional construct? EJPA, 18(3), 242-251."},
        ],
        "citations": [
            {"title": "Generalized Self-Efficacy Scale", "authors": "Schwarzer, R., & Jerusalem, M.", "year": 1995, "doi": "10.1037/t00393-000"},
        ],
        "language": "zh",
    },
]

ENTRIES_SEED: list[dict] = [
    {
        "title": "问卷设计方法论",
        "category": "methodology_guide",
        "content": {
            "sections": [
                {"heading": "基本原则", "body": "问卷设计应遵循 AAPOR（美国舆论研究协会）最佳实践：问题应清晰、中立、单一维度。避免引导性问题、双重否定和过于复杂的句式。"},
                {"heading": "题型选择", "body": "根据构念类型选择：态度/意见用 Likert 量表；行为频率用排序或频率量表；知识用是非题/选择题；人口统计学用标准分类。"},
                {"heading": "量表长度", "body": "建议每个构念至少 3 个题项以保证内部一致性。总量表建议 20-30 题，完成时间 10-15 分钟。过长的问卷会降低回复质量和完成率。"},
                {"heading": "预测试", "body": "正式发放前应进行认知访谈（5-8 人）和预测试（30-50 人）。预测试数据可用于初步信效度分析和题项修订。"},
            ],
        },
        "tags": ["问卷设计", "方法论", "AAPOR", "预测试"],
        "language": "zh",
    },
    {
        "title": "信效度检验指南",
        "category": "methodology_guide",
        "content": {
            "sections": [
                {"heading": "信度 (Reliability)", "body": "内部一致性：Cronbach's α ≥ 0.70 可接受，≥ 0.80 良好，≥ 0.90 优秀。重测信度：间隔 2-4 周，ICC ≥ 0.75 可接受。折半信度：Spearman-Brown 校正。"},
                {"heading": "效度 (Validity)", "body": "内容效度：专家评审 + CVI 指数 ≥ 0.80。结构效度：探索性因子分析（EFA）+ 验证性因子分析（CFA），CFI ≥ 0.90，RMSEA ≤ 0.08。效标关联效度：与已有金标准量表的相关性。"},
                {"heading": "区分效度", "body": "使用 AVE（平均方差提取）比较法，AVE 平方根 > 构念间相关系数则区分效度良好。HTMT（异质-单质比率）< 0.85 为宜。"},
                {"heading": "统计分析工具", "body": "SPSS（信度分析/EFA）、AMOS/Mplus（CFA）、R（lavaan/semTools）。本平台内置 Cronbach's α 和基础 EFA。"},
            ],
        },
        "tags": ["信效度", "Cronbach's α", "因子分析", "CFA", "测量学"],
        "language": "zh",
    },
    {
        "title": "抽样方法概述",
        "category": "methodology_guide",
        "content": {
            "sections": [
                {"heading": "概率抽样", "body": "简单随机抽样：每个个体等概率被选。分层抽样：按关键变量分层后随机抽取，提高代表性。整群抽样：以自然群体（班级/医院/社区）为单位抽取。多阶段抽样：逐级缩小抽样范围，适合全国性调查。"},
                {"heading": "非概率抽样", "body": "便利抽样：快速但对总体代表性低。配额抽样：按人口学变量分层后便利抽样。滚雪球抽样：适合罕见人群。目的性抽样：定性研究常用。"},
                {"heading": "样本量计算", "body": "基本公式：n = Z²×p×(1-p)/e²。常用参数：95% 置信水平 Z=1.96，误差界限 e=0.05，p=0.5（保守估计）。考虑 20% 无效率，最终 n ≈ 384×(1+0.2) ≈ 460。"},
                {"heading": "在线调查抽样偏差", "body": "在线调查面临覆盖偏差（非网民排除）和自我选择偏差。建议采用多模式招募（邮件+社交媒体+短信）并加权后调整。"},
            ],
        },
        "tags": ["抽样", "样本量", "概率抽样", "非概率抽样", "在线调查"],
        "language": "zh",
    },
    {
        "title": "共同方法偏差控制",
        "category": "best_practice",
        "content": {
            "sections": [
                {"heading": "什么是共同方法偏差 (CMB)", "body": "当自变量和因变量均来自同一受访者的自我报告时，变量间相关可能被人为放大。CMB 是行为科学研究中最常见的方法学威胁之一（Podsakoff et al., 2003）。"},
                {"heading": "程序性控制", "body": "1) 时间分离：分两时点收集自变量和因变量；2) 心理分离：使用封面故事降低偏差；3) 匿名保证：明确告知匿名性和无对错之分；4) 题目随机化：打乱题目顺序，降低顺序效应；5) 反向计分：混入反向题项打破默许反应。"},
                {"heading": "统计控制", "body": "1) Harman 单因子检验：未旋转因子分析，第一个因子方差解释 < 50% 则 CMB 不严重；2) ULMC 法：在 CFA 中加入共同方法因子；3) 标记变量法：加入理论上无关的标记变量偏相关。"},
            ],
        },
        "tags": ["共同方法偏差", "CMB", "方法学", "测量误差", "Podsakoff"],
        "language": "zh",
    },
    {
        "title": "PIPL 合规要点",
        "category": "best_practice",
        "content": {
            "sections": [
                {"heading": "法律依据", "body": "《中华人民共和国个人信息保护法》（PIPL）于 2021 年 11 月 1 日生效。学术调查属于个人信息处理活动，需遵守 PIPL 各项要求。"},
                {"heading": "知情同意", "body": "收集个人信息前必须获得明示同意（Article 14）。同意书需包含：处理目的、处理方式、信息类型、保存期限、数据主体权利。学术调查建议在问卷首页设置同意复选框（opt-in），不可预填。"},
                {"heading": "最小化原则", "body": "仅收集研究目的所需的必要信息。避免收集身份证号、精确地址、生物识别等敏感信息，除非有明确的学术必要性并获得单独同意（Article 28）。"},
                {"heading": "数据本土化", "body": "中国公民的个人信息原则上应存储在中国境内服务器。如需跨境传输，需进行安全评估或签订标准合同条款（Article 38）。"},
                {"heading": "数据主体权利", "body": "受访者有权查阅、更正、删除其个人信息，并有权撤回同意（Article 44-47）。平台需提供便捷的撤回机制。"},
                {"heading": "处罚", "body": "违法行为罚款上限：5000 万元或上年度营业额的 5%（Article 66）。情节严重者可吊销营业执照。"},
            ],
        },
        "tags": ["PIPL", "合规", "知情同意", "数据保护", "中国法律"],
        "language": "zh",
    },
    {
        "title": "量表翻译与跨文化调适指南",
        "category": "methodology_guide",
        "content": {
            "sections": [
                {"heading": "翻译流程", "body": "推荐 WHO 标准翻译流程：1) 正向翻译（2 名独立双语翻译员）；2) 专家组评审合并为一个版本；3) 反向翻译（英语母语者将目标语言版本翻回原语言）；4) 预测试（30-50 名目标人群）和认知访谈。"},
                {"heading": "跨文化效度", "body": "翻译不等于跨文化调适。需考虑：概念等价（构念在两种文化中意义相同）、语义等价（词汇含义一致）、操作等价（量表形式和施测方式可比）。"},
                {"heading": "常见陷阱", "body": "习语直译（如 'feeling blue' 不能直译为 '感觉蓝色'）；文化特定概念（如 'individualism' 在某些集体主义文化中无直接对应）；回答量表的文化差异（某些文化倾向于极端值/中间值）。"},
                {"heading": "验证策略", "body": "多组 CFA 检验测量不变性（configural → metric → scalar → strict）。DIF（差别项目功能）分析：使用 IRT 或 logistic 回归法检测跨文化偏差的项目。"},
            ],
        },
        "tags": ["量表翻译", "跨文化", "翻译", "测量不变性", "DIF"],
        "language": "zh",
    },
]


async def seed_scales_and_entries(db: AsyncSession) -> None:
    """Populate knowledge_scales and knowledge_entries if they are empty.

    Safe to call on every startup — checks row counts before inserting.
    """
    # Only seed if tables are empty
    scale_count = (await db.execute(select(func.count(KnowledgeScale.id)))).scalar() or 0
    if scale_count == 0:
        for data in SCALES_SEED:
            scale = KnowledgeScale(
                id=str(uuid.uuid4()),
                name=data["name"],
                discipline=data["discipline"],
                description=data.get("description"),
                items=data.get("items"),
                cronbach_alpha=data.get("cronbach_alpha"),
                cronbach_alpha_history=data.get("cronbach_alpha_history"),
                citations=data.get("citations"),
                language=data.get("language", "zh"),
                source_type="manual",
            )
            db.add(scale)
        await db.flush()

    entry_count = (await db.execute(select(func.count(KnowledgeEntry.id)))).scalar() or 0
    if entry_count == 0:
        for data in ENTRIES_SEED:
            entry = KnowledgeEntry(
                id=str(uuid.uuid4()),
                title=data["title"],
                category=data["category"],
                content=data.get("content"),
                tags=data.get("tags"),
                language=data.get("language", "zh"),
                is_published=True,
            )
            db.add(entry)
        await db.flush()
