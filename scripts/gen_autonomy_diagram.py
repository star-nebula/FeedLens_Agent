"""Generate FeedLens_Autonomy_Architecture.drawio — 自主性决策架构图"""
import xml.sax.saxutils as saxutils

def esc(s):
    return saxutils.escape(s)

xml = '''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="65bd71144e">
    <diagram id="autonomy" name="FeedLens 自主性架构">
        <mxGraphModel dx="80" dy="-30" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400" pageHeight="950" math="0" shadow="0">
            <root>
                <mxCell id="0"/>
                <mxCell id="1" parent="0"/>

                <!-- ====== TITLE ====== -->
                <mxCell id="title" value="FeedLens 自主性决策架构 — 哪里体现了「Agent 自主」" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=20;fontStyle=1;fontColor=#1a1a2e;" parent="1" vertex="1">
                    <mxGeometry x="280" y="20" width="840" height="35" as="geometry"/>
                </mxCell>

                <!-- ====== LAYER 1: 触发自主 ====== -->
                <mxCell id="l1_bg" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E3F2FD;strokeColor=#1565C0;strokeWidth=2;dashed=1;opacity=20;" parent="1" vertex="1">
                    <mxGeometry x="60" y="75" width="1280" height="100" as="geometry"/>
                </mxCell>
                <mxCell id="l1_label" value="第一层：触发自主 — 系统自己唤醒自己" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=13;fontStyle=1;fontColor=#1565C0;" parent="1" vertex="1">
                    <mxGeometry x="75" y="80" width="350" height="22" as="geometry"/>
                </mxCell>
                <mxCell id="scheduler" value="APScheduler&#xa;CronTrigger&#xa;(定时自动触发)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#BBDEFB;strokeColor=#1976D2;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#0D47A1;align=center;" parent="1" vertex="1">
                    <mxGeometry x="200" y="108" width="170" height="55" as="geometry"/>
                </mxCell>
                <mxCell id="breaking_news" value="异常检测&#xa;(Breaking News&#xa;score&gt;0.85 自主破例)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#BBDEFB;strokeColor=#1976D2;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#0D47A1;align=center;" parent="1" vertex="1">
                    <mxGeometry x="520" y="108" width="180" height="55" as="geometry"/>
                </mxCell>
                <mxCell id="label_passive2active" value="被动 → 主动 的关键跃迁" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#1976D2;fontStyle=2;" parent="1" vertex="1">
                    <mxGeometry x="850" y="125" width="200" height="20" as="geometry"/>
                </mxCell>

                <!-- scheduler → breaking_news 表示两种触发路径汇聚 -->
                <mxCell id="e_sched_to" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#1976D2;endFill=1;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="370" y="135" as="sourcePoint"/>
                        <mxPoint x="520" y="135" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- ====== LAYER 2: 决策自主 ====== -->
                <mxCell id="l2_bg" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF3E0;strokeColor=#E65100;strokeWidth=2;dashed=1;opacity=20;" parent="1" vertex="1">
                    <mxGeometry x="60" y="200" width="1280" height="280" as="geometry"/>
                </mxCell>
                <mxCell id="l2_label" value="第二层：决策自主 — ReAct 循环，每次路由都是动态决策" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=13;fontStyle=1;fontColor=#E65100;" parent="1" vertex="1">
                    <mxGeometry x="75" y="205" width="400" height="22" as="geometry"/>
                </mxCell>

                <!-- 理解意图 -->
                <mxCell id="nd_understand" value="understand_intent&#xa;(LLM 理解目标 → structured_goal)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="100" y="240" width="230" height="55" as="geometry"/>
                </mxCell>

                <!-- Planner（核心自主节点） -->
                <mxCell id="nd_planner" value="📌 Planner&#xa;自主编排子Agent调用计划&#xa;从记忆学习历史经验" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFCC80;strokeColor=#E65100;strokeWidth=3;fontSize=13;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="430" y="232" width="260" height="70" as="geometry"/>
                </mxCell>

                <!-- Router（动态路由） -->
                <mxCell id="nd_router" value="📌 Router&#xa;LLM 动态决策下一步&#xa;fallback 规则兜底" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF9C4;strokeColor=#F57F17;strokeWidth=3;fontSize=12;fontStyle=1;fontColor=#F57F17;align=center;" parent="1" vertex="1">
                    <mxGeometry x="790" y="232" width="230" height="70" as="geometry"/>
                </mxCell>

                <!-- Reflect（质量自主） -->
                <mxCell id="nd_reflect" value="📌 coordinator_reflect&#xa;自主判断质量是否达标&#xa;不达标 → 重排，达标 → 推送" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="790" y="350" width="260" height="70" as="geometry"/>
                </mxCell>

                <!-- 内存记忆读取 -->
                <mxCell id="mem_read_label" value="自主记忆检索" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#F3E5F5;strokeColor=#7B1FA2;strokeWidth=1.5;dashed=1;fontSize=11;fontStyle=1;fontColor=#6A1B9A;align=center;" parent="1" vertex="1">
                    <mxGeometry x="440" y="370" width="120" height="25" as="geometry"/>
                </mxCell>

                <!-- Push -->
                <mxCell id="nd_push" value="push_notification&#xa;(自主推送)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1120" y="350" width="180" height="55" as="geometry"/>
                </mxCell>

                <!-- 中止 -->
                <mxCell id="nd_abort" value="abort&#xa;(自主中止)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFCDD2;strokeColor=#C62828;strokeWidth=2;fontSize=12;fontColor=#C62828;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1120" y="248" width="120" height="55" as="geometry"/>
                </mxCell>

                <!-- ===== 边：Layer 2 内部 ====== -->

                <!-- understand → planner -->
                <mxCell id="e1" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="330" y="267" as="sourcePoint"/>
                        <mxPoint x="430" y="267" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- planner → router -->
                <mxCell id="e2" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="690" y="267" as="sourcePoint"/>
                        <mxPoint x="790" y="267" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- router → invoke (fallback 90%) -->
                <mxCell id="e_rtr_fb" value="fallback (90%) 规则直通" style="endArrow=block;html=1;strokeWidth=1.5;strokeColor=#F57F17;dashed=1;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;" parent="1" source="nd_router" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="905" y="330" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- router → invoke (LLM 10%) -->
                <mxCell id="e_rtr_llm" value="LLM 决策 (10%)" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.7;exitDx=0;exitDy=0;" parent="1" source="nd_router" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1020" y="290" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- Invoke 标注 -->
                <mxCell id="label_invoke" value="→ invoke_sub_agent" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#E65100;fontStyle=2;" parent="1" vertex="1">
                    <mxGeometry x="870" y="310" width="140" height="18" as="geometry"/>
                </mxCell>

                <!-- router → reflect -->
                <mxCell id="e_rtr_ref" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" source="nd_router" target="nd_reflect" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>

                <!-- router → push -->
                <mxCell id="e_rtr_push" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#4CAF50;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;" parent="1" source="nd_router" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1120" y="267" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- router → abort -->
                <mxCell id="e_rtr_abort" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#C62828;endFill=1;exitX=1;exitY=0.2;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" source="nd_router" target="nd_abort" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>

                <!-- reflect → push (quality >= 0.7) -->
                <mxCell id="e_ref_pass" value="quality >= 0.7 → 通过" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#4CAF50;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" source="nd_reflect" target="nd_push" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>

                <!-- reflect → router (quality < 0.7, retry < 2) -->
                <mxCell id="e_ref_fail" value="quality &lt; 0.7 → 退回重排 (最多2次)" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#D84315;dashed=1;endFill=1;exitX=0;exitY=0.3;exitDx=0;exitDy=0;entryX=0;entryY=1;entryDx=0;entryDy=0;" parent="1" source="nd_reflect" target="nd_router" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="740" y="370"/>
                            <mxPoint x="740" y="310"/>
                        </Array>
                    </mxGeometry>
                </mxCell>

                <!-- 记忆读取 → planner -->
                <mxCell id="e_mem_read" value="检索近7天执行记录 + 语义匹配历史经验" style="endArrow=block;html=1;strokeWidth=1.5;strokeColor=#7B1FA2;dashed=1;endFill=1;exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" source="mem_read_label" target="nd_planner" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="500" y="360"/>
                            <mxPoint x="560" y="360"/>
                        </Array>
                    </mxGeometry>
                </mxCell>

                <!-- ReAct 循环标注 -->
                <mxCell id="react_note" value="⬆ ReAct 自主循环：planner ↔ router … 最多3轮" style="text;html=1;strokeColor=none;fillColor=#FFF8E1;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=12;fontStyle=1;fontColor=#E65100;rounded=1;strokeWidth=1;strokeColor=#E65100;" parent="1" vertex="1">
                    <mxGeometry x="590" y="440" width="340" height="25" as="geometry"/>
                </mxCell>

                <!-- ====== LAYER 3: 进化自主 ====== -->
                <mxCell id="l3_bg" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E8F5E9;strokeColor=#2E7D32;strokeWidth=2;dashed=1;opacity=20;" parent="1" vertex="1">
                    <mxGeometry x="60" y="510" width="1280" height="130" as="geometry"/>
                </mxCell>
                <mxCell id="l3_label" value="第三层：进化自主 — 越用越聪明（反馈闭环）" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=13;fontStyle=1;fontColor=#2E7D32;" parent="1" vertex="1">
                    <mxGeometry x="75" y="515" width="350" height="22" as="geometry"/>
                </mxCell>

                <!-- 反馈Agent -->
                <mxCell id="nd_feedback" value="FeedbackAgent&#xa;收集用户反馈 → EMA(α=0.3)&#xa;更新偏好向量 v_like / v_dislike" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#C8E6C9;strokeColor=#388E3C;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#1B5E20;align=center;" parent="1" vertex="1">
                    <mxGeometry x="200" y="550" width="260" height="70" as="geometry"/>
                </mxCell>

                <!-- 偏好向量存储 -->
                <mxCell id="nd_prefs" value="用户偏好向量 (ChromaDB)&#xa;v_like / v_dislike&#xa;排序Agent 读取此数据" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#C8E6C9;strokeColor=#43A047;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#1B5E20;align=center;" parent="1" vertex="1">
                    <mxGeometry x="600" y="550" width="240" height="70" as="geometry"/>
                </mxCell>

                <!-- 进化说明 -->
                <mxCell id="evolve_note" value="反馈 → 偏好向量变化 → 下轮排序结果不同 → 「越用越知道自己想要什么」" style="text;html=1;strokeColor=none;fillColor=#E8F5E9;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=12;fontStyle=1;fontColor=#2E7D32;rounded=1;strokeWidth=1;strokeColor=#2E7D32;" parent="1" vertex="1">
                    <mxGeometry x="950" y="555" width="360" height="40" as="geometry"/>
                </mxCell>

                <!-- feedback → prefs -->
                <mxCell id="e_fb_pref" value="EMA 更新" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#388E3C;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" source="nd_feedback" target="nd_prefs" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>

                <!-- prefs → 排序Agent 说明 -->
                <mxCell id="e_pref_rank" value="下一轮排序引用" style="endArrow=block;html=1;strokeWidth=1.5;strokeColor=#43A047;dashed=1;endFill=1;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="720" y="585" as="sourcePoint"/>
                        <mxPoint x="930" y="585" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- ====== 跨层连接 ====== -->
                <!-- 触发 → 理解 -->
                <mxCell id="e_trigger" value="" style="endArrow=block;html=1;strokeWidth=2.5;strokeColor=#546E7A;endFill=1;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="285" y="163" as="sourcePoint"/>
                        <mxPoint x="215" y="240" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>

                <!-- push → feedback -->
                <mxCell id="e_push_fb" value="推送后收集反馈" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#546E7A;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" source="nd_push" target="nd_feedback" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="1210" y="420"/>
                            <mxPoint x="330" y="420"/>
                        </Array>
                    </mxGeometry>
                </mxCell>

                <!-- ====== 底部总结 ====== -->
                <mxCell id="summary_bg" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ECEFF1;strokeColor=#607D8B;strokeWidth=1.5;" parent="1" vertex="1">
                    <mxGeometry x="60" y="670" width="1280" height="95" as="geometry"/>
                </mxCell>
                <mxCell id="summary_label" value="总结：三层自主性" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=14;fontStyle=1;fontColor=#37474F;" parent="1" vertex="1">
                    <mxGeometry x="80" y="678" width="200" height="22" as="geometry"/>
                </mxCell>
                <mxCell id="summary_t1" value="1. 触发自主 — 不是等人来用，系统自己按 cron 定时醒来干活（被动→主动）" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#1565C0;" parent="1" vertex="1">
                    <mxGeometry x="80" y="702" width="560" height="18" as="geometry"/>
                </mxCell>
                <mxCell id="summary_t2" value="2. 决策自主 — 每次 router 动态决策下一步，不是固定的 A→B→C 管线，reflect 自主判断质量够了没有" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#E65100;" parent="1" vertex="1">
                    <mxGeometry x="80" y="722" width="600" height="18" as="geometry"/>
                </mxCell>
                <mxCell id="summary_t3" value="3. 进化自主 — 用户反馈 EMA 更新偏好向量，下轮排序自动变化，越用越精准" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#2E7D32;" parent="1" vertex="1">
                    <mxGeometry x="80" y="742" width="560" height="18" as="geometry"/>
                </mxCell>
                <mxCell id="vs_label" value="vs 工作流 Agent" style="text;html=1;strokeColor=none;fillColor=#FFF3E0;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=13;fontStyle=1;fontColor=#BF360C;rounded=1;strokeWidth=1;strokeColor=#E65100;" parent="1" vertex="1">
                    <mxGeometry x="780" y="680" width="130" height="25" as="geometry"/>
                </mxCell>
                <mxCell id="vs_content" value="工作流 Agent: 流程固定 (A→B→C), 出错也硬走到底&#xa;FeedLens: 每次路由动态决定下一步, 质量不够就回头重排" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#37474F;" parent="1" vertex="1">
                    <mxGeometry x="780" y="708" width="540" height="40" as="geometry"/>
                </mxCell>

            </root>
        </mxGraphModel>
    </diagram>
</mxfile>'''

with open('docs/architecture/FeedLens_Autonomy_Architecture.drawio', 'w', encoding='utf-8') as f:
    f.write(xml)

import os
size = os.path.getsize('docs/architecture/FeedLens_Autonomy_Architecture.drawio')
print(f"OK: FeedLens_Autonomy_Architecture.drawio ({size} bytes)")
