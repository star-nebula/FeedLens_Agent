#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate FeedLens_Simple_Architecture2.drawio
Updated architecture diagram with 5 key fixes:
1. understand_intent as proper independent node
2. router_node (LLM dynamic routing) added and highlighted
3. coordinator_reflect as independent node
4. Breaking News trigger path detailed
5. FeedbackAgent properly represented
"""

content = """<mxfile host="65bd71144e">
    <diagram id="simple-arch2" name="FeedLens Architecture v3 (Code-Aligned)">
        <mxGraphModel dx="70" dy="-32" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="2200" pageHeight="1400" math="0" shadow="0">
            <root>
                <mxCell id="0"/>
                <mxCell id="1" parent="0"/>
                
                <!-- Title -->
                <mxCell id="title" value="FeedLens Agent 核心运行流程 — 与代码完全对齐版 v3" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=22;fontStyle=1;fontColor=#1a1a2e;" parent="1" vertex="1">
                    <mxGeometry x="2200" y="30" width="1000" height="35" as="geometry"/>
                </mxCell>
                
                <!-- ==================== Layer 1: Input Layer ==================== -->
                <mxCell id="l1_box" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E3F2FD;strokeColor=#1565C0;strokeWidth=2;dashed=1;opacity=25;" parent="1" vertex="1">
                    <mxGeometry x="100" y="100" width="2080" height="110" as="geometry"/>
                </mxCell>
                <mxCell id="l1_title" value="&#x1F4E1; 输入层：从哪里来？" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=14;fontStyle=1;fontColor=#1565C0;" parent="1" vertex="1">
                    <mxGeometry x="115" y="105" width="280" height="25" as="geometry"/>
                </mxCell>
                
                <!-- Input sources -->
                <mxCell id="in_timer" value="&#x23F0; APScheduler&#x200B;CronTrigger&#x200B;&#x23F0;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#BBDEFB;strokeColor=#1976D2;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#0D47A1;" parent="1" vertex="1">
                    <mxGeometry x="120" y="138" width="200" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="in_manual" value="&#x1F464; 手动触发&#x200B;(Streamlit UI)&#x200B;&#x1F464;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#BBDEFB;strokeColor=#1976D2;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#0D47A1;" parent="1" vertex="1">
                    <mxGeometry x="360" y="138" width="200" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="in_breaking" value="&#x1F6A8; Breaking News&#x200B;破例触发&#x200B;&#x1F6A8;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFCDD2;strokeColor=#C62828;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#B71C1C;" parent="1" vertex="1">
                    <mxGeometry x="600" y="138" width="220" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="in_datasource" value="&#x1F4F0; 数据源&#x200B;RSS / 网页 / API&#x200B;&#x1F4F0;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#BBDEFB;strokeColor=#1976D2;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#0D47A1;" parent="1" vertex="1">
                    <mxGeometry x="860" y="138" width="220" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="in_mcp" value="&#x1F5A5; MCP SSE:8100&#x200B;搜索补充数据源&#x200B;&#x1F5A5;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E1BEE7;strokeColor=#7B1FA2;strokeWidth=1.5;fontSize=11;fontStyle=1;fontColor=#4A148C;" parent="1" vertex="1">
                    <mxGeometry x="1100" y="138" width="220" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="in_config" value="&#x2699; config.yaml&#x200B;阈值参数配置&#x200B;&#x2699;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F0F4C3;strokeColor=#827717;strokeWidth=1.5;fontSize=11;fontStyle=1;fontColor=#33691E;" parent="1" vertex="1">
                    <mxGeometry x="1340" y="138" width="200" height="44" as="geometry"/>
                </mxCell>
                
                <!-- Breaking News detail -->
                <mxCell id="bn_detail" value="Ranking Agent 检测:&#x200B;score&gt;0.85 &amp; freshness&lt;2h &#x2192; push_immediate=True&#x2192;" style="text;html=1;strokeColor=#C62828;fillColor=#FFEBEE;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=10;fontColor=#B71C1C;rounded=1;" parent="1" vertex="1">
                    <mxGeometry x="600" y="192" width="350" height="18" as="geometry"/>
                </mxCell>
                
                <!-- Arrow: Input -> understand_intent -->
                <mxCell id="arr_input" value="" style="endArrow=block;html=1;strokeWidth=2.5;strokeColor=#1565C0;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1200" y="248" as="sourcePoint"/>
                        <mxPoint x="1200" y="280" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- ==================== Layer 2: Brain Decision Layer ==================== -->
                <mxCell id="l2_box" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF3E0;strokeColor=#E65100;strokeWidth=2.5;dashed=1;opacity=30;" parent="1" vertex="1">
                    <mxGeometry x="100" y="280" width="2080" height="330" as="geometry"/>
                </mxCell>
                <mxCell id="l2_title" value="&#x1F9E0; 大脑决策层 (LangGraph StateGraph &#x2014; 8个节点)" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=14;fontStyle=1;fontColor=#E65100;" parent="1" vertex="1">
                    <mxGeometry x="115" y="285" width="450" height="25" as="geometry"/>
                </mxCell>
                
                <!-- Node 1: understand_intent -->
                <mxCell id="nd_understand" value="&#x2460; understand_intent&#x200B;(LLM&#x63D0;&#x53D6; structured_goal&#x200B;+ goal_embedding)&#x2460;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#E65100;strokeWidth=2.5;fontSize=12;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="140" y="330" width="280" height="56" as="geometry"/>
                </mxCell>
                
                <!-- Node 2: planner -->
                <mxCell id="nd_planner" value="&#x2461; planner (ReAct loop)&#x200B;&#x1F9E0; &#x8BFB; &#x8BB0;&#x5FC6;&#x8F85;&#x52A9;&#x51B3;&#x7B56;&#x200B;&#x1F9E0;&#x2461;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF8E1;strokeColor=#E65100;strokeWidth=3;fontSize=12;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="500" y="328" width="240" height="60" as="geometry"/>
                </mxCell>
                
                <!-- Node 3: router_node (NEW - highlighted) -->
                <mxCell id="nd_router" value="&#x2462; router_node &#x1F6A8;NEW&#x1F6A8;&#x200B;(LLM&#x52A8;&#x6001;&#x8DEF;&#x7531; decision)&#x200B;&#x2462;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF9C4;strokeColor=#F57F17;strokeWidth=3;fontSize=12;fontStyle=1;fontColor=#F57F17;align=center;" parent="1" vertex="1">
                    <mxGeometry x="810" y="328" width="260" height="60" as="geometry"/>
                </mxCell>
                
                <!-- Node 4: invoke_sub_agent -->
                <mxCell id="nd_invoke" value="&#x2463; invoke_sub_agent&#x200B;(run_with_isolation &#x5F02;&#x5E38;&#x9694;&#x79BB;)&#x200B;&#x2463;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=1.5;fontSize=11;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1140" y="330" width="220" height="56" as="geometry"/>
                </mxCell>
                
                <!-- Node 5: observe_results -->
                <mxCell id="nd_observe" value="&#x2464; observe_results&#x200B;(&#x89C2;&#x5BDF;&#x7ED3;&#x679C; &#x2192; router &#x6761;&#x4EF6;&#x8DEF;&#x7531;)&#x200B;&#x2464;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=1.5;fontSize=11;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1430" y="330" width="220" height="56" as="geometry"/>
                </mxCell>
                
                <!-- Node 6: coordinator_reflect (NEW independent) -->
                <mxCell id="nd_reflect" value="&#x2465; coordinator_reflect &#x1F6A8;NEW&#x1F6A8;&#x200B;(&#x7EFC;&#x5408;&#x5BA1;&#x67E5; quality&lt;0.7 &#x2192; &#x9000;&#x56DE;planner)&#x200B;&#x2465;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFCCBC;strokeColor=#D84315;strokeWidth=3;fontSize=11;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1710" y="328" width="280" height="60" as="geometry"/>
                </mxCell>
                
                <!-- Node 7: push_notification -->
                <mxCell id="nd_push" value="&#x2466; push_notification&#x200B;(MCP stdio &#x63A8;&#x9001;&#x901A;&#x77E5;)&#x200B;&#x2466;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=1.5;fontSize=11;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="500" y="430" width="240" height="50" as="geometry"/>
                </mxCell>
                
                <!-- Node 8: update_memory -->
                <mxCell id="nd_memory" value="&#x2467; update_memory&#x200B;(SQLite + ChromaDB &#x540C;&#x6B65;&#x5199;&#x5165;)&#x200B;&#x2467;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#F57C00;strokeWidth=1.5;fontSize=11;fontStyle=1;fontColor=#BF360C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="810" y="430" width="260" height="50" as="geometry"/>
                </mxCell>
                
                <!-- fallback_router arrow -->
                <mxCell id="arr_fallback" value="fallback_router_decision()&#x200B;(90%&#x6B63;&#x5E38;&#x6D41; &#x8DF3;&#x8FC7;LLM)&#x200B;" style="endArrow=none;html=1;strokeWidth=1.5;strokeColor=#F57F17;dashed=1;endFill=0;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1200" y="410" as="sourcePoint"/>
                        <mxPoint x="1200" y="505" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- Edges between brain nodes -->
                <!-- understand_intent -> planner -->
                <mxCell id="e_und_pln" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_understand" target="nd_planner">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>
                
                <!-- planner -> router_node -->
                <mxCell id="e_pln_rtr" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_planner" target="nd_router">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>
                
                <!-- router_node -> invoke_sub_agent -->
                <mxCell id="e_rtr_inv" value="decision=invoke" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_router" target="nd_invoke">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>
                
                <!-- invoke_sub_agent -> observe_results -->
                <mxCell id="e_inv_obs" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_invoke" target="nd_observe">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>
                
                <!-- observe_results -> router_node (loop back) -->
                <mxCell id="e_obs_rtr" value="decision=planner" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#D84315;endFill=1;dashed=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.3;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_observe" target="nd_router">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="1700" y="358"/>
                            <mxPoint x="1700" y="290"/>
                            <mxPoint x="940" y="290"/>
                        </Array>
                    </mxGeometry>
                </mxCell>
                
                <!-- observe_results -> coordinator_reflect -->
                <mxCell id="e_obs_ref" value="decision=reflect" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_observe" target="nd_reflect">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>
                
                <!-- coordinator_reflect -> planner (quality < 0.7, retry < 2) -->
                <mxCell id="e_ref_pln" value="&#x2716; quality&lt;0.7 &#x2192; &#x9000;&#x56DE;planner" style="endArrow=block;html=1;strokeWidth=2.5;strokeColor=#D84315;endFill=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_reflect" target="nd_planner">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="1600" y="358"/>
                            <mxPoint x="1600" y="290"/>
                            <mxPoint x="620" y="290"/>
                        </Array>
                    </mxGeometry>
                </mxCell>
                
                <!-- coordinator_reflect -> push_notification (quality >= 0.7) -->
                <mxCell id="e_ref_psh" value="&#x2705; quality&#x2265;0.7 &#x2192; &#x63A8;&#x9001;" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#2E7D32;endFill=1;exitX=0;exitY=0.8;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_reflect" target="nd_push">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1620" y="468" as="sourcePoint"/>
                        <mxPoint x="620" y="455" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- push_notification -> update_memory -->
                <mxCell id="e_psh_mem" value="" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#E65100;endFill=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_push" target="nd_memory">
                    <mxGeometry width="50" height="50" relative="1" as="geometry"/>
                </mxCell>
                
                <!-- ReAct loop annotation -->
                <mxCell id="react_label" value="ReAct &#x5FAA;&#x73AF;: planner &#x2194; router &#x2194; invoke &#x2194; observe &#x2194; reflect &#x2194; planner (&#x6700;&#x591A;3&#x6B21;)" style="text;html=1;strokeColor=none;fillColor=#FFF3E0;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontStyle=2;fontColor=#D84315;rounded=1;" parent="1" vertex="1">
                    <mxGeometry x="700" y="560" width="600" height="20" as="geometry"/>
                </mxCell>
                
                <!-- Arrow: Brain -> Sub Agents -->
                <mxCell id="arr_brain_down" value="" style="endArrow=block;html=1;strokeWidth=2.5;strokeColor=#546E7A;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1200" y="620" as="sourcePoint"/>
                        <mxPoint x="1200" y="650" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- ==================== Layer 3: Sub-Agent Execution Layer ==================== -->
                <mxCell id="l3_box" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E8F5E9;strokeColor=#2E7D32;strokeWidth=2;dashed=1;opacity=25;" parent="1" vertex="1">
                    <mxGeometry x="100" y="650" width="2080" height="130" as="geometry"/>
                </mxCell>
                <mxCell id="l3_title" value="&#x1F916; &#x5B50;Agent &#x6267;&#x884C;&#x5C42; (run_with_isolation &#x5F02;&#x5E38;&#x9694;&#x79BB;)" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=14;fontStyle=1;fontColor=#2E7D32;" parent="1" vertex="1">
                    <mxGeometry x="115" y="655" width="450" height="25" as="geometry"/>
                </mxCell>
                
                <mxCell id="sa_collect" value="&#x1F4E1; Collection Agent&#x200B;(RSS&#x6293;&#x53D6; + &#x7F51;&#x9875;&#x722C;&#x866B;)&#x200B;&#x1F4E1;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#C8E6C9;strokeColor=#388E3C;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#1B5E20;align=center;" parent="1" vertex="1">
                    <mxGeometry x="160" y="690" width="240" height="52" as="geometry"/>
                </mxCell>
                <mxCell id="sa_rank" value="&#x1F3C6; Ranking Agent&#x200B;(&#x591A;&#x56E0;&#x5B50;&#x6392;&#x5E8F; + &#x50A8;&#x5B58;&#x504F;&#x597D;)&#x200B;&#x1F3C6;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#C8E6C9;strokeColor=#388E3C;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#1B5E20;align=center;" parent="1" vertex="1">
                    <mxGeometry x="480" y="690" width="260" height="52" as="geometry"/>
                </mxCell>
                <mxCell id="sa_brief" value="&#x1F4DD; Briefing Agent&#x200B;(LLM&#x751F;&#x6210;&#x7B80;&#x62A5; + &#x8D28;&#x91CF;&#x8BC4;&#x5206;)&#x200B;&#x1F4DD;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#C8E6C9;strokeColor=#388E3C;strokeWidth=2;fontSize=12;fontStyle=1;fontColor=#1B5E20;align=center;" parent="1" vertex="1">
                    <mxGeometry x="810" y="690" width="260" height="52" as="geometry"/>
                </mxCell>
                <mxCell id="sa_feedback" value="&#x1F4AC; FeedbackAgent &#x1F6A8;NEW&#x1F6A8;&#x200B;(&#x6536;&#x96C6;&#x53CD;&#x9988; + feedback_bias + EMA)&#x200B;&#x1F4AC;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DCEDC8;strokeColor=#689F38;strokeWidth=2.5;fontSize=12;fontStyle=1;fontColor=#33691E;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1140" y="690" width="280" height="52" as="geometry"/>
                </mxCell>
                
                <!-- Edge: router -> sub-agents (dashed, indicating dispatch) -->
                <mxCell id="e_rtr_sa" value="planner &#x8C03;&#x5EA6;" style="endArrow=block;html=1;strokeWidth=1.5;strokeColor=#388E3C;endFill=1;dashed=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="940" y="490" as="sourcePoint"/>
                        <mxPoint x="940" y="558" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- Breaking News edge: Ranking -> push (bypass normal flow) -->
                <mxCell id="e_bn_push" value="&#x26A1; breaking news &#x7ACB;&#x5373;&#x63A8;&#x9001;" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#C62828;endFill=1;dashed=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.3;entryDx=0;entryDy=0;" parent="1" edge="1" source="sa_rank" target="nd_push">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="900" y="716"/>
                            <mxPoint x="900" y="500"/>
                            <mxPoint x="620" y="500"/>
                        </Array>
                    </mxGeometry>
                </mxCell>
                
                <mxCell id="arr_sa_down" value="" style="endArrow=block;html=1;strokeWidth=2.5;strokeColor=#546E7A;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1200" y="800" as="sourcePoint"/>
                        <mxPoint x="1200" y="830" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- ==================== Layer 4: Memory System Layer ==================== -->
                <mxCell id="l4_box" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F3E5F5;strokeColor=#7B1FA2;strokeWidth=2;dashed=1;opacity=25;" parent="1" vertex="1">
                    <mxGeometry x="100" y="830" width="2080" height="210" as="geometry"/>
                </mxCell>
                <mxCell id="l4_title" value="&#x1F4BE; &#x8BB0;&#x5FC6;&#x7CFB;&#x7EDF;&#x5C42; (&#x53CC;&#x5C42;&#x67B6;&#x6784; WAL&#x6A21;&#x5F0F;)" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=14;fontStyle=1;fontColor=#7B1FA2;" parent="1" vertex="1">
                    <mxGeometry x="115" y="835" width="500" height="25" as="geometry"/>
                </mxCell>
                
                <!-- SQLite episodic memory -->
                <mxCell id="mem_sqlite" value="&#x1F4DD; &#x60C5;&#x8282;&#x8BB0;&#x5FC6; (SQLite)&#x200B;execution_logs &#x8868;&#x200B;&#x5B58;&#x50A8;&#x8FD1;7&#x5929;&#x6267;&#x884C;&#x65E5;&#x5FD7;&#x200B;&#x1F4DD;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E1BEE7;strokeColor=#8E24AA;strokeWidth=2;fontSize=11;fontStyle=1;fontColor=#4A148C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="140" y="875" width="310" height="60" as="geometry"/>
                </mxCell>
                
                <!-- ChromaDB long-term memory -->
                <mxCell id="mem_chroma" value="&#x1F4DA; &#x957F;&#x671F;&#x8BB0;&#x5FC6; (ChromaDB)&#x200B;LLM &#x6458;&#x8981;200&#x5B57; &#x2192; &#x76F4;&#x63A5;&#x5199;&#x5165;&#x200B;&#x8BED;&#x4E49;&#x68C0;&#x7D22;&#x5339;&#x914D;&#x5386;&#x53F2;&#x573A;&#x666F;&#x200B;&#x1F4DA;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E1BEE7;strokeColor=#8E24AA;strokeWidth=2;fontSize=11;fontStyle=1;fontColor=#4A148C;align=center;" parent="1" vertex="1">
                    <mxGeometry x="520" y="875" width="340" height="60" as="geometry"/>
                </mxCell>
                
                <!-- User preference vectors -->
                <mxCell id="mem_pref" value="&#x2B50; &#x7528;&#x6237;&#x504F;&#x597D; (ChromaDB)&#x200B;v_like / v_dislike &#x5411;&#x91CF;&#x200B;&#x6392;&#x5E8F;Agent &#x8BC4;&#x5206;&#x4F9D;&#x636E;&#x200B;EMA(&#x03B1;=0.3) &#x5F02;&#x6B65;&#x66F4;&#x65B0;&#x200B;&#x2B50;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F3E5F5;strokeColor=#AB47BC;strokeWidth=2;fontSize=11;fontStyle=1;fontColor=#6A1B9A;align=center;" parent="1" vertex="1">
                    <mxGeometry x="930" y="875" width="360" height="60" as="geometry"/>
                </mxCell>
                
                <!-- Sorting formula -->
                <mxCell id="mem_formula" value="&#x1F4D0; &#x6392;&#x5E8F;&#x516C;&#x5F0F;: final_score = w1&#xB7;similarity + w2&#xB7;recency + w3&#xB7;(preference+feedback_bias) + w4&#xB7;importance&#x1F4D0;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#EDE7F6;strokeColor=#7B1FA2;strokeWidth=1.5;fontSize=10;fontColor=#7B1FA2;align=center;" parent="1" vertex="1">
                    <mxGeometry x="140" y="955" width="1150" height="30" as="geometry"/>
                </mxCell>
                
                <!-- Memory read edges (planner reads from memory) -->
                <mxCell id="e_mem_read1" value="&#x1F4D6; &#x8BFB; SQLite" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#8E24AA;endFill=1;exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=0.3;entryY=1;entryDx=0;entryDy=0;" parent="1" edge="1" source="mem_sqlite" target="nd_planner">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="295" y="850"/>
                            <mxPoint x="568" y="850"/>
                        </Array>
                        <mxPoint x="295" y="618" as="sourcePoint"/>
                        <mxPoint x="568" y="388" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                <mxCell id="e_mem_read2" value="&#x1F4D6; &#x8BFB; ChromaDB" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#8E24AA;endFill=1;exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=0.5;entryY=1;entryDx=0;entryDy=0;" parent="1" edge="1" source="mem_chroma" target="nd_planner">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="690" y="850"/>
                            <mxPoint x="620" y="850"/>
                        </Array>
                        <mxPoint x="690" y="618" as="sourcePoint"/>
                        <mxPoint x="620" y="388" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- Memory write edges (update_memory writes to both) -->
                <mxCell id="e_mem_write1" value="&#x270F; &#x5199; SQLite" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#8E24AA;endFill=1;exitX=0;exitY=0.3;exitDx=0;exitDy=0;entryX=0.5;entryY=1;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_memory" target="mem_sqlite">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="810" y="445"/>
                            <mxPoint x="295" y="445"/>
                        </Array>
                        <mxPoint x="295" y="935" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                <mxCell id="e_mem_write2" value="&#x270F; &#x5199; ChromaDB" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#8E24AA;endFill=1;exitX=0.2;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=1;entryDx=0;entryDy=0;" parent="1" edge="1" source="nd_memory" target="mem_chroma">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="862" y="480"/>
                            <mxPoint x="690" y="480"/>
                        </Array>
                        <mxPoint x="690" y="935" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- FeedbackAgent writes preference -->
                <mxCell id="e_fb_write" value="&#x270F; &#x5199;&#x504F;&#x597D;" style="endArrow=block;html=1;strokeWidth=2;strokeColor=#689F38;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=1;entryDx=0;entryDy=0;" parent="1" edge="1" source="sa_feedback" target="mem_pref">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <Array as="points">
                            <mxPoint x="1280" y="870"/>
                            <mxPoint x="1110" y="870"/>
                        </Array>
                        <mxPoint x="1110" y="935" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- Ranking Agent reads preference -->
                <mxCell id="e_rank_read" value="&#x1F4D6; &#x8BFB;&#x504F;&#x597D;" style="endArrow=block;html=1;strokeWidth=1.5;strokeColor=#689F38;endFill=1;exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;" parent="1" edge="1" source="mem_pref" target="sa_rank">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1110" y="935" as="sourcePoint"/>
                        <mxPoint x="610" y="716" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <mxCell id="arr_mem_down" value="" style="endArrow=block;html=1;strokeWidth=2.5;strokeColor=#546E7A;endFill=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" parent="1" edge="1">
                    <mxGeometry width="50" height="50" relative="1" as="geometry">
                        <mxPoint x="1200" y="1060" as="sourcePoint"/>
                        <mxPoint x="1200" y="1090" as="targetPoint"/>
                    </mxGeometry>
                </mxCell>
                
                <!-- ==================== Layer 5: Output Layer ==================== -->
                <mxCell id="l5_box" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#E0F7FA;strokeColor=#00695C;strokeWidth=2;dashed=1;opacity=25;" parent="1" vertex="1">
                    <mxGeometry x="100" y="1090" width="2080" height="100" as="geometry"/>
                </mxCell>
                <mxCell id="l5_title" value="&#x1F4E2; &#x8F93;&#x51FA;&#x5C42;: &#x7528;&#x6237;&#x770B;&#x5230;&#x4EC0;&#x4E48;&#xFF1F;" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=14;fontStyle=1;fontColor=#00695C;" parent="1" vertex="1">
                    <mxGeometry x="115" y="1095" width="300" height="25" as="geometry"/>
                </mxCell>
                
                <mxCell id="out_dashboard" value="&#x1F4CA; Streamlit &#x4FE1;&#x606F;&#x4EEA;&#x8868;&#x76D8;&#x200B;&#x67E5;&#x770B;&#x7B80;&#x62A5; + &#x5386;&#x53F2;&#x8BB0;&#x5F55;&#x200B;&#x1F4CA;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#B2DFDB;strokeColor=#00796B;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#004D40;align=center;" parent="1" vertex="1">
                    <mxGeometry x="160" y="1130" width="340" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="out_push" value="&#x1F6A8; &#x63A8;&#x9001;&#x901A;&#x77E5;&#x200B;(MCP stdio &#x5B9E;&#x65F6;&#x63A8;&#x9001;&#x5230;&#x7528;&#x6237;&#x7AEF;)&#x200B;&#x1F6A8;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#B2DFDB;strokeColor=#00796B;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#004D40;align=center;" parent="1" vertex="1">
                    <mxGeometry x="560" y="1130" width="380" height="44" as="geometry"/>
                </mxCell>
                <mxCell id="out_history" value="&#x1F4CB; &#x5386;&#x53F2;&#x56DE;&#x987E;&#x200B;(&#x6807;&#x6CE8;&#x6536;&#x85CF; + &#x53CD;&#x9988;&#x8BB0;&#x5F55;)&#x200B;&#x1F4CB;" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#B2DFDB;strokeColor=#00796B;strokeWidth=2;fontSize=13;fontStyle=1;fontColor=#004D40;align=center;" parent="1" vertex="1">
                    <mxGeometry x="1000" y="1130" width="300" height="44" as="geometry"/>
                </mxCell>
                
                <!-- ==================== Memory Interaction Legend ==================== -->
                <mxCell id="legend_box" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ECEFF1;strokeColor=#607D8B;strokeWidth=1.5;dashed=1;opacity=40;" parent="1" vertex="1">
                    <mxGeometry x="100" y="1220" width="2080" height="65" as="geometry"/>
                </mxCell>
                <mxCell id="legend_title" value="&#x1F4D6; &#x8BFB;&#x5199;&#x56FE;&#x4F8B;" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=13;fontStyle=1;fontColor=#546E7A;" parent="1" vertex="1">
                    <mxGeometry x="115" y="1225" width="150" height="22" as="geometry"/>
                </mxCell>
                <mxCell id="legend_read" value="&#x1F4D6; &#x5B9E;&#x7EBF;&#x7D2B;&#x7BAD;&#x5934; = &#x8BFB;&#x53D6;&#x8BB0;&#x5FC6; (planner&#x4ECE;SQLite/ChromaDB&#x68C0;&#x7D22;)" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#8E24AA;" parent="1" vertex="1">
                    <mxGeometry x="280" y="1225" width="420" height="22" as="geometry"/>
                </mxCell>
                <mxCell id="legend_write" value="&#x270F; &#x5B9E;&#x7EBF;&#x7D2B;&#x7BAD;&#x5934; = &#x5199;&#x5165;&#x8BB0;&#x5FC6; (update_memory &#x5199;SQLite+ChromaDB)" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#8E24AA;" parent="1" vertex="1">
                    <mxGeometry x="720" y="1225" width="450" height="22" as="geometry"/>
                </mxCell>
                <mxCell id="legend_iso" value="&#x1F6A8; &#x9EC4;&#x8272;&#x8282;&#x70B9; = v3&#x65B0;&#x589E;/&#x91CD;&#x7ED8; (router_node / coordinator_reflect / FeedbackAgent)" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#F57F17;" parent="1" vertex="1">
                    <mxGeometry x="280" y="1250" width="550" height="22" as="geometry"/>
                </mxCell>
                <mxCell id="legend_bn" value="&#x26A1; &#x7EA2;&#x8272;&#x865A;&#x7EBF; = Breaking News &#x7ACB;&#x5373;&#x63A8;&#x9001;&#x8DEF;&#x5F84;" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#C62828;" parent="1" vertex="1">
                    <mxGeometry x="850" y="1250" width="400" height="22" as="geometry"/>
                </mxCell>
                
                <!-- Summary text -->
                <mxCell id="summary" value="&#x1F4A1; FeedLens = &#x4E3B;&#x52A8;&#x5F0F;&#x4FE1;&#x606F;&#x805A;&#x5408;Agent: &#x5B9A;&#x65F6;/&#x7AEF;&#x70B9;&#x89E6;&#x53D1; &#x2192; planner(ReAct)&#x8C03;&#x5EA6;sub-Agent &#x2192; &#x6392;&#x5E8F;+&#x7B80;&#x62A5;+&#x53CD;&#x9988; &#x2192; &#x68C0;&#x67E5;&#x8D28;&#x91CF; &#x2192; &#x63A8;&#x9001;&#x5F02;&#x6B65;&#x66F4;&#x65B0;&#x8BB0;&#x5FC6; &#x2192; &#x201C;&#x8D8A;&#x7528;&#x8D8A;&#x806A;&#x660E;&#x201D;&#x6B63;&#x5411;&#x5FAA;&#x73AF;&#x1F4A1;" style="text;html=1;strokeColor=#37474F;fillColor=#ECEFF1;align=center;verticalAlign=middle;whiteSpace=wrap;fontSize=12;fontStyle=2;fontColor=#37474F;rounded=1;strokeWidth=1.5;" parent="1" vertex="1">
                    <mxGeometry x="140" y="1310" width="2000" height="40" as="geometry"/>
                </mxCell>
                
            </root>
        </mxGraphModel>
    </diagram>
</mxfile>
"""

output_path = r"E:\BaiduSyncdisk\Project\heima-lesson\LLM_Projects\FeedLens_Agent\docs\architecture\FeedLens_Simple_Architecture2.drawio"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"SUCCESS: Written to {output_path}")
print(f"File size: {len(content.encode('utf-8'))} bytes")
