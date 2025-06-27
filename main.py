from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import os,json,datetime
import json
import requests
from astrbot.api.event.filter import event_message_type, EventMessageType
import numpy as np
from datetime import datetime
import json
from astrbot.api.all import *

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from scipy.interpolate import make_interp_spline
from openai import OpenAI
from PIL import Image as ImageW
import logging

@register("astrbot_plugin_get_weather", "whzc", "获取12小时的天气并生成一张图片", "1.1.0", "repo url")

class Main(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        # 加载配置文件
        self.config = config
        
        # 初始化实例变量
        self.dashscope_api_key = self.config.get("dashscope_api_key", "")
        self.qweather_api_key = self.config.get("qweather_api_key", "")
        self.wake_msg = self.config.get("wake_msg", "天气&&查询天气").split("&&")
        self.model_name = self.config.get("model_name", "qwen-turbo")
        self.history_access = bool(self.config.get("history_access", False))
        self.ai_base_url = self.config.get("ai_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.qweather_api_base_url=self.config.get("qweather_api_base_url", "geoapi.qweather.com")
        
        # 用户位置存储
        import os
        self.user_locations_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_locations.json")
        self.user_locations = self.load_user_locations()
        
        # 设置日志文件
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.debug_log_file = os.path.join(self.plugin_dir, "weather_debug.log")
        
        # 配置文件日志记录器
        self.file_logger = logging.getLogger('weather_plugin_file')
        self.file_logger.setLevel(logging.DEBUG)
        if not self.file_logger.handlers:
            file_handler = logging.FileHandler(self.debug_log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            self.file_logger.addHandler(file_handler)
            self.file_logger.propagate = False
    
    def log_info(self, message, console=True):
        """记录信息日志，可选择是否在控制台显示"""
        self.file_logger.info(message)
        if console:
            logger.info(message)
    
    def log_debug(self, message, console=False):
        """记录调试日志，默认只写入文件"""
        self.file_logger.debug(message)
        if console:
            logger.info(message)
    
    def log_error(self, message, console=True):
        """记录错误日志，默认在控制台显示"""
        self.file_logger.error(message)
        if console:
            logger.error(message)
    
    async def get_user_context_via_astrbot(self, event):
        """通过AstrBot框架获取用户上下文信息"""
        try:
            if not self.history_access:
                self.log_debug("历史消息访问功能未启用")
                return {}
            
            self.log_debug("尝试通过AstrBot框架获取用户历史消息...")
            
            # 获取用户ID
            user_id = getattr(event, 'unified_msg_origin', 'unknown')
            current_message = event.get_message_str()
            
            # 获取会话管理器
            conversation_mgr = self.context.conversation_manager
            
            # 获取当前会话ID
            curr_cid = await conversation_mgr.get_curr_conversation_id(user_id)
            self.log_debug(f"获取到当前会话ID: {curr_cid}")
            
            if not curr_cid:
                self.log_debug("用户没有当前会话，无法获取历史消息")
                return {}
            
            # 获取会话对象
            conversation = await conversation_mgr.get_conversation(user_id, curr_cid)
            self.log_debug(f"获取到会话对象: {conversation is not None}")
            
            if not conversation:
                self.log_debug("会话对象为空，无法获取历史消息")
                return {}
            
            # 解析历史消息
            try:
                history = json.loads(conversation.history) if conversation.history else []
                self.log_debug(f"解析到历史消息数量: {len(history)}")
                
                # 创建详细的历史消息日志文件
                import os
                from datetime import datetime
                
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                log_file = os.path.join(plugin_dir, "history_messages.log")
                
                # 记录详细的历史消息到日志文件和控制台
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_content = f"\n{'='*60}\n[{timestamp}] 用户 {user_id} 的历史消息分析\n{'='*60}\n"
                
                for i, msg in enumerate(history):
                    msg_info = f"消息 #{i+1}: "
                    if isinstance(msg, dict):
                        # 详细解析字典格式的消息
                        msg_info += f"类型={type(msg).__name__}, "
                        for key, value in msg.items():
                            if key in ['content', 'message', 'text', 'role', 'timestamp', 'time']:
                                msg_info += f"{key}={repr(value)[:100]}, "
                    else:
                        msg_info += f"类型={type(msg).__name__}, 内容={repr(str(msg))[:100]}"
                    
                    log_content += msg_info + "\n"
                    self.log_debug(f"历史消息 #{i+1}: {msg_info}")
                
                log_content += f"\n总计 {len(history)} 条历史消息\n"
                
                # 写入日志文件
                try:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(log_content)
                    self.log_debug(f"历史消息详情已写入日志文件: {log_file}")
                except Exception as e:
                    self.log_error(f"写入日志文件失败: {e}", console=False)
                
                # 分析最近几条消息中的位置信息
                recent_messages = history[-10:] if len(history) > 10 else history
                location_contexts = []  # 记录地名及其完整上下文
                activity_hints = []
                
                self.log_debug(f"开始分析最近 {len(recent_messages)} 条消息...")
                
                for i, msg in enumerate(recent_messages):
                    content = ""
                    msg_role = ""
                    if isinstance(msg, dict):
                        content = msg.get('content', '') or str(msg.get('message', '')) or str(msg.get('text', ''))
                        msg_role = msg.get('role', 'unknown')
                    else:
                        content = str(msg)
                        msg_role = 'unknown'
                    
                    self.log_debug(f"分析消息 #{i+1} (角色:{msg_role}): {repr(content)[:50]}...")
                    
                    # 检测地点提及 - 使用更智能的检测方式
                    found_locations = []
                    # 扩展城市列表，包含更多中国城市
                    cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都", "重庆", "西安", "天津", "沈阳", 
                             "嘉兴", "苏州", "无锡", "常州", "宁波", "温州", "台州", "金华", "绍兴", "湖州", "衢州", "舟山", "丽水"]
                    for location in cities:
                        if location in content:
                            # 记录地名及其完整上下文
                            location_contexts.append({
                                "location": location,
                                "content": content,
                                "role": msg_role,
                                "message_index": i + 1
                            })
                            found_locations.append(location)
                    
                    # 如果没有找到精确匹配，尝试更精确的地名后缀匹配
                    if not found_locations:
                        try:
                            import re
                            # 匹配更复杂的地名模式，包括"市+区"的组合
                            location_patterns = [
                                rf'([^。，,\s]{2,6}[市][^。，,\s]{2,6}[区县])',  # 如"嘉兴市南湖区"
                                rf'([^。，,\s]{2,6}[南北东西中][^。，,\s]{1,3}[区县])',  # 如"嘉兴南湖区"
                                rf'([^。，,\s]{2,8}[市区县镇村街道省州盟])'  # 一般地名后缀
                            ]
                            
                            for pattern in location_patterns:
                                matches = re.findall(pattern, content)
                                for match in matches:
                                    if (len(match) >= 3 and 
                                        match not in [loc["location"] for loc in location_contexts] and
                                        not any(invalid in match for invalid in ['的', '了', '呢', '吗', '啊'])):
                                        location_contexts.append({
                                            "location": match,
                                            "content": content,
                                            "role": msg_role,
                                            "message_index": i + 1
                                        })
                                        found_locations.append(match)
                                        break  # 找到一个精确匹配就停止
                        except:
                            pass
                    
                    if found_locations:
                        self.log_debug(f"  - 发现地点: {found_locations}")
                    
                    # 检测活动线索
                    found_activities = []
                    if any(word in content for word in ["在家", "家里", "家中"]):
                        activity_hints.append("在家")
                        found_activities.append("在家")
                    elif any(word in content for word in ["出门", "外面", "路上", "公司", "办公室"]):
                        activity_hints.append("在外")
                        found_activities.append("在外")
                    elif any(word in content for word in ["刚起床", "准备出门", "要出去"]):
                        activity_hints.append("准备出门")
                        found_activities.append("准备出门")
                    
                    if found_activities:
                        self.log_debug(f"  - 发现活动: {found_activities}")
                
                # 记录详细的地名上下文分析
                for loc_context in location_contexts:
                    self.log_debug(f"地名上下文 - 地点:{loc_context['location']}, 角色:{loc_context['role']}, 消息:{repr(loc_context['content'])[:80]}")
                
                # 只保留有效的地名
                valid_location_contexts = []
                for loc_context in location_contexts:
                    location = loc_context["location"]
                    if (len(location) >= 2 and 
                        not any(invalid in location for invalid in ['的', '了', '呢', '？', '?', '！', '!', '，', ',', '。', '.']) and
                        location not in ['Human', 'it', 'can', 'some', 'the', 'what', 'me', 'so', 'that', 'does', 'with', 'at']):
                        valid_location_contexts.append(loc_context)
                
                context_data = {
                    "location_status": activity_hints[-1] if activity_hints else "不确定",
                    "activity_hints": list(set(activity_hints[-3:])),  # 最近3个活动提示
                    "time_relevance": f"历史消息显示最近的活动状态",
                    "location_contexts": valid_location_contexts,  # 完整的地名上下文
                    "recent_mentions": [ctx["location"] for ctx in valid_location_contexts[-3:]]  # 最近3个有效地点提及
                }
                
                # 记录分析结果到日志文件
                analysis_result = f"\n分析结果:\n"
                analysis_result += f"  - 位置状态: {context_data['location_status']}\n"
                analysis_result += f"  - 活动线索: {context_data['activity_hints']}\n"
                analysis_result += f"  - 地点提及: {context_data['recent_mentions']}\n"
                analysis_result += f"  - 时间相关: {context_data['time_relevance']}\n"
                
                try:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(analysis_result + "\n")
                except Exception as e:
                    self.log_error(f"写入分析结果失败: {e}", console=False)
                
                self.log_info(f"分析结果汇总:", console=False)
                self.log_info(f"  - 发现地名上下文数量: {len(valid_location_contexts)}", console=False)
                self.log_info(f"  - 有效地点提及: {context_data['recent_mentions']}", console=False)
                self.log_debug(f"  - 找到活动: {list(set(activity_hints))}")
                self.log_info(f"AstrBot历史分析成功: {context_data}", console=False)
                return context_data
                
            except (json.JSONDecodeError, TypeError) as e:
                self.log_error(f"解析历史消息失败: {e}")
                return {}
                
        except Exception as e:
            self.log_error(f"AstrBot上下文分析失败: {e}")
            return {}

    def load_user_locations(self):
        """加载用户位置数据"""
        try:
            if os.path.exists(self.user_locations_file):
                with open(self.user_locations_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.log_error(f"加载用户位置数据失败: {e}")
        return {}
    
    def save_user_locations(self):
        """保存用户位置数据"""
        try:
            with open(self.user_locations_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_locations, f, ensure_ascii=False, indent=2)
            self.log_debug("用户位置数据已保存")
        except Exception as e:
            self.log_error(f"保存用户位置数据失败: {e}")
    
    def get_user_confirmed_location(self, user_id):
        """获取用户已确认的位置"""
        return self.user_locations.get(user_id, {}).get('confirmed_location')
    
    def update_user_confirmed_location(self, user_id, location, source="manual"):
        """更新用户确认的位置"""
        if user_id not in self.user_locations:
            self.user_locations[user_id] = {}
        
        self.user_locations[user_id]['confirmed_location'] = location
        self.user_locations[user_id]['last_update'] = datetime.now().isoformat()
        self.user_locations[user_id]['source'] = source  # manual/auto
        
        self.save_user_locations()
        self.log_info(f"更新用户 {user_id} 的确认位置: {location}", console=False)
    
    async def analyze_user_context(self, event, query_location, user_confirmed_location=None):
        """分析用户上下文，区分查询地点和用户实际位置"""
        try:
            self.log_debug("开始分析用户上下文...")
            self.log_debug(f"查询地点: {query_location}, 用户确认位置: {user_confirmed_location}")
            
            # 获取当前时间信息
            now = datetime.now()
            current_hour = now.hour
            current_minute = now.minute
            is_weekday = now.weekday() < 5  # 0-4 是工作日
            
            # 获取当前消息
            user_message = event.get_message_str()
            
            # 通过AstrBot获取更深入的上下文分析
            ai_context = {}
            if self.history_access:
                self.log_debug("history_access已启用，开始通过AstrBot获取历史消息")
                ai_context = await self.get_user_context_via_astrbot(event)
                self.log_debug(f"AstrBot历史分析完成，结果: {ai_context}")
            else:
                self.log_debug("history_access未启用，跳过历史消息获取")
            
            # 分析时间段
            time_analysis = ""
            if 5 <= current_hour < 8:
                time_analysis = "清晨时段，用户可能刚起床或准备出门"
            elif 8 <= current_hour < 9:
                if is_weekday:
                    time_analysis = "工作日早高峰，用户可能在通勤路上"
                else:
                    time_analysis = "周末早晨，用户可能还在家中"
            elif 9 <= current_hour < 12:
                if is_weekday:
                    time_analysis = "工作日上午，用户可能在办公室"
                else:
                    time_analysis = "周末上午，用户可能在家或外出"
            elif 12 <= current_hour < 14:
                time_analysis = "午餐时间，用户可能在外就餐或办公室"
            elif 14 <= current_hour < 18:
                if is_weekday:
                    time_analysis = "工作日下午，用户可能在办公室"
                else:
                    time_analysis = "周末下午，用户可能在外活动"
            elif 18 <= current_hour < 20:
                if is_weekday:
                    time_analysis = "工作日傍晚，用户可能在下班路上或刚到家"
                else:
                    time_analysis = "周末傍晚，用户可能在外或在家"
            elif 20 <= current_hour < 23:
                time_analysis = "晚上时段，用户可能在家中"
            else:
                time_analysis = "深夜时段，用户可能在家中"
            
            # 分析当前消息中的位置线索
            location_clues = []
            if any(word in user_message for word in ["在家", "家里", "家中"]):
                location_clues.append("用户明确提到在家")
            elif any(word in user_message for word in ["出门", "外面", "路上", "公司", "办公室"]):
                location_clues.append("用户可能在外面")
            elif any(word in user_message for word in ["刚起床", "准备出门", "要出去"]):
                location_clues.append("用户可能准备出门或刚起床")
            elif any(word in user_message for word in ["下班", "回家", "到家"]):
                location_clues.append("用户可能在回家路上或刚到家")
            
            # 整合AI分析的上下文信息
            if ai_context:
                if ai_context.get('location_status') and ai_context['location_status'] != '不确定':
                    location_clues.append(f"AI分析：用户{ai_context['location_status']}")
                
                if ai_context.get('activity_hints'):
                    location_clues.extend([f"可能在{hint}" for hint in ai_context['activity_hints'][:2]])
                
                if ai_context.get('recent_mentions'):
                    location_clues.extend([f"最近提到：{mention}" for mention in ai_context['recent_mentions'][:2]])
            
            # 确定用户当前实际位置
            user_actual_location = user_confirmed_location or "未知"
            
            context_info = {
                "current_time": f"{current_hour:02d}:{current_minute:02d}",
                "is_weekday": is_weekday,
                "time_analysis": time_analysis,
                "location_clues": location_clues,
                "user_message": user_message,
                "query_location": query_location,  # 查询的地点
                "user_actual_location": user_actual_location,  # 用户实际位置
                "is_same_location": (query_location == user_actual_location),  # 是否查询自己所在地
                "ai_context": ai_context  # 保存AI分析结果
            }
            
            self.log_debug(f"上下文分析结果: {context_info}")
            return context_info
            
        except Exception as e:
            self.log_error(f"用户上下文分析失败: {e}")
            return {
                "current_time": "未知",
                "is_weekday": True,
                "time_analysis": "无法判断用户当前状态",
                "location_clues": [],
                "user_message": event.get_message_str() if event else "",
                "query_location": query_location,
                "user_actual_location": user_confirmed_location or "未知",
                "is_same_location": False,
                "ai_context": {}
            }

    async def get_weather_advice(self, current_weather, next_few_hours, event=None, location="", user_input=""):
        """根据天气情况生成关心提示和颜文字"""
        return await self.get_ai_weather_advice(current_weather, next_few_hours, "hourly", event, location, user_input)
    
    async def get_weather_advice_current(self, current_weather, event=None, location="", user_input=""):
        """根据实时天气情况生成关心提示和颜文字"""
        return await self.get_ai_weather_advice(current_weather, None, "current", event, location, user_input)
    
    async def extract_user_specific_question(self, user_input):
        """提取用户的具体问题类型"""
        try:
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': '分析用户的天气相关问题，提取用户关心的具体方面。例如："热不热"关心温度，"冷吗"关心寒冷，"下雨吗"关心降雨，"需要带伞吗"关心降雨防护，"适合出门吗"关心整体天气适宜性。如果是一般性询问就回复"一般"。只返回关键词：温度|寒冷|降雨|防护|适宜性|一般'},
                    {'role': 'user', 'content': user_input}
                ]
            )
            
            question_type = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            self.log_debug(f"用户问题类型: {question_type}")
            return question_type
            
        except Exception as e:
            self.log_error(f"问题类型提取失败: {e}")
            return "一般"
    
    def detect_extreme_weather(self, current_weather, next_few_hours=None):
        """检测极端天气情况"""
        try:
            current_temp = int(current_weather['temp'])
            current_text = current_weather['text']
            
            extreme_conditions = []
            
            # 极端温度
            if current_temp >= 40:
                extreme_conditions.append("酷暑高温")
            elif current_temp <= -20:
                extreme_conditions.append("严寒低温")
            elif current_temp <= -10:
                extreme_conditions.append("寒潮")
            
            # 危险天气现象
            dangerous_weather = ["暴雨", "大暴雨", "特大暴雨", "台风", "龙卷风", "冰雹", "暴雪", "大暴雪", "沙尘暴", "雷暴"]
            for weather in dangerous_weather:
                if weather in current_text:
                    extreme_conditions.append(weather)
            
            # 检查未来几小时是否有极端天气
            if next_few_hours:
                for hour_data in next_few_hours[:6]:
                    hour_text = hour_data['text']
                    for weather in dangerous_weather:
                        if weather in hour_text and weather not in extreme_conditions:
                            extreme_conditions.append(f"即将{weather}")
            
            if extreme_conditions:
                alert_message = "、".join(extreme_conditions)
                self.log_debug(f"检测到极端天气: {alert_message}")
                return alert_message
            
            return None
            
        except Exception as e:
            self.log_error(f"极端天气检测失败: {e}")
            return None

    async def get_ai_weather_advice(self, current_weather, next_few_hours=None, weather_type="current", event=None, location="", user_input=""):
        """使用AI根据实际天气情况和用户上下文生成个性化关心提示"""
        try:
            self.log_debug("开始使用AI生成天气关心提示...")
            
            # 提取用户的具体问题
            question_type = await self.extract_user_specific_question(user_input) if user_input else "一般"
            
            # 获取用户ID和确认位置
            user_id = getattr(event, 'unified_msg_origin', 'unknown') if event else 'unknown'
            user_confirmed_location = self.get_user_confirmed_location(user_id)
            
            # 分析用户上下文，区分查询地点和用户位置
            context = await self.analyze_user_context(event, location, user_confirmed_location) if event else {}
            
            # 准备天气数据
            current_temp = int(current_weather['temp'])
            current_text = current_weather['text']
            
            # 构建自然的天气描述，避免重复数字
            weather_info = current_text
            
            # 只在极端天气时提及具体温度
            extreme_weather = False
            if current_temp >= 35:  # 高温
                weather_info += f"，{current_temp}度高温"
                extreme_weather = True
            elif current_temp <= 0:  # 冰点
                weather_info += f"，{current_temp}度严寒" 
                extreme_weather = True
            elif current_temp <= 5:  # 很冷
                weather_info += "，很冷"
            elif current_temp >= 30:  # 很热
                weather_info += "，很热"
            elif current_temp <= 10:  # 比较冷
                weather_info += "，有点冷"
            elif current_temp >= 25:  # 比较热
                weather_info += "，比较热"
            
            if weather_type == "current" and 'feelsLike' in current_weather:
                feels_like = int(current_weather.get('feelsLike', current_temp))
                humidity = current_weather.get('humidity', 'N/A')
                
                # 体感差异描述
                temp_diff = feels_like - current_temp
                if temp_diff >= 5:
                    weather_info += "，感觉特别闷热"
                elif temp_diff >= 3:
                    weather_info += "，有点闷"
                elif temp_diff <= -5:
                    weather_info += "，风比较大"
                elif temp_diff <= -3:
                    weather_info += "，有风"
                
                # 湿度描述
                if humidity != 'N/A':
                    humidity_val = int(humidity)
                    if humidity_val > 80:
                        weather_info += "，很闷"
                    elif humidity_val > 70:
                        weather_info += "，比较闷"
                    elif humidity_val < 20:
                        weather_info += "，很干燥"
                    elif humidity_val < 30:
                        weather_info += "，空气干燥"
            
            if weather_type == "hourly" and next_few_hours:
                upcoming_weathers = [item['text'] for item in next_few_hours[1:3]]
                upcoming_temps = [int(item['temp']) for item in next_few_hours[1:3]]
                
                # 温度变化趋势
                if upcoming_temps:
                    temp_change = max(upcoming_temps) - current_temp
                    if temp_change > 5:
                        weather_info += "，一会儿会更热"
                    elif temp_change > 2:
                        weather_info += "，温度还会升高"
                    elif temp_change < -5:
                        weather_info += "，待会儿会凉快不少"
                    elif temp_change < -2:
                        weather_info += "，温度会降一些"
                
                # 天气变化
                if any("雨" in w for w in upcoming_weathers) and "雨" not in current_text:
                    weather_info += "，稍后可能下雨"
                elif "雨" in current_text and not any("雨" in w for w in upcoming_weathers):
                    weather_info += "，雨一会儿就停"
                elif any("雪" in w for w in upcoming_weathers) and "雪" not in current_text:
                    weather_info += "，可能会下雪"
            
            # 调用AI生成个性化建议
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            system_prompt = """你是用户的好朋友，自然地聊天分享天气情况和关心建议。

核心要求：
1. 必须提及关键天气信息（下雨、大太阳、下雪、低温、台风、高温等）
2. 用朋友聊天的语气，自然随意，不要像客服、助手或AI
3. 根据用户的时间、位置上下文给出合适的建议，避免逻辑矛盾
4. 根据天气情况自然地使用颜文字表达关心（不要用emoji表情）
5. 避免"建议"、"提醒"、"请注意"等正式用语，用"记得"、"别忘了"等朋友式表达
6. 重要：在回答中自然地提及用户查询的具体地名，让地名融入朋友间的关心话语
7. 用户问题类型：{question_type} - 请针对用户的具体问题给出相应回答

针对不同问题类型的回答要求：
- 温度类问题：根据实际温度数据判断热或冷，给出具体的温度感受和建议
- 寒冷类问题：重点说明是否寒冷及保暖建议
- 降雨类问题：重点说明是否下雨及是否需要雨具
- 防护类问题：重点说明需要什么防护措施
- 适宜性问题：综合天气情况判断是否适合外出活动
- 一般问题：简洁地描述天气情况和温度感受，不要过多建议，重点关心天气和温度本身

上下文判断原则：
- 如果用户查询的是自己所在地的天气（query_location == user_actual_location）：给出针对用户当前状态的生活建议
- 如果用户查询的是其他地方的天气：主要描述该地天气情况，不要给出太多生活建议
- 如果用户实际位置未知：给出通用的天气描述和建议
- 避免假设用户在查询地点，除非已确认用户在该地

颜文字使用指南：
- 担心的天气（暴雨、台风、大雪、极端天气）可以用关心担心类：(｡•́︿•̀｡) (´｡• ᵕ •｡`) ♡
- 温和提醒时用温暖关怀类：(´∀｀)♡ ｡◕‿◕｡ (◍•ᴗ•◍) 
- 叮嘱安全时用注意安全类：(•̀ᴗ•́)و ̑̑ (｡♡‿♡｡) ( ˘ ³˘)♥
- 寒冷天气关怀用保暖关心类：(つ≧▽≦)つ ♡(>ᴗ•) (っ˘̩╭╮˘̩)っ
- 也可以不用颜文字，如果句子本身已经很温暖

回复风格：
 查询自己所在地："嘉兴这边下雨了，你在外面的话记得找个地方避一下雨，出门别忘了带伞哦～"
 查询自己所在地："你那边下雪了呢，要出门的话记得多穿点，路上小心别滑倒 (´｡• ᵕ •｡`) ♡"
 查询其他地方："杭州现在是晴天，26度挺舒服的呢～"
 查询其他地方："上海那边多云，15度有点凉，感觉像秋天的温度 (◍•ᴗ•◍)"

重点：用朋友聊天的自然语气，根据上下文判断用户状态，避免逻辑冲突。"""

            # 检测极端天气
            extreme_weather_alert = self.detect_extreme_weather(current_weather, next_few_hours)
            
            # 构建包含上下文的用户消息
            context_message = f"{location}的天气是{weather_info}。温度：{current_temp}度。"
            if extreme_weather_alert:
                context_message += f" 【极端天气警告】{extreme_weather_alert}"
            if context:
                context_message += f" 补充信息：当前时间{context['current_time']}，"
                context_message += f"{'工作日' if context['is_weekday'] else '周末'}，"
                context_message += f"{context['time_analysis']}。"
                if context['location_clues']:
                    context_message += f" 用户状态线索：{', '.join(context['location_clues'])}。"
                context_message += f" 用户原始消息：'{context['user_message']}'。"
                context_message += f" 查询地点：{context['query_location']}。"
                if context['user_actual_location'] != "未知":
                    context_message += f" 用户实际位置：{context['user_actual_location']}。"
                    if context['is_same_location']:
                        context_message += f" 用户查询的是自己所在地的天气。"
                    else:
                        context_message += f" 用户查询的不是自己所在地，而是其他地方的天气。"
                else:
                    context_message += f" 用户实际位置未知。"
                # 添加AI分析的额外上下文
                if context.get('ai_context'):
                    ai_ctx = context['ai_context']
                    if ai_ctx.get('time_relevance'):
                        context_message += f" AI时间分析：{ai_ctx['time_relevance']}。"
            context_message += f" 用户问题类型：{question_type}。请给我一些实用的生活建议，并在回答中自然地提及地名。"
            
            self.log_debug(f"发送给AI的上下文消息: {context_message}")
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': context_message}
                ]
            )
            
            ai_advice = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            self.log_info(f"AI天气建议生成成功", console=False)
            self.log_debug(f"AI建议内容: {ai_advice[:50]}...")
            
            return ai_advice
            
        except Exception as e:
            self.log_error(f"AI天气建议生成失败: {e}")
            self.log_debug("降级使用固定天气建议")
            # 降级方案
            return self.get_fallback_weather_advice(current_weather, next_few_hours, weather_type)
    
    def get_fallback_weather_advice(self, current_weather, next_few_hours=None, weather_type="current"):
        """降级方案：使用固定的天气建议"""
        current_temp = int(current_weather['temp'])
        current_text = current_weather['text']
        
        advice = ""
        
        # 根据温度给出建议
        if current_temp <= 0:
            advice += "🥶 天气很冷呢，记得多穿点衣服保暖哦～\n"
        elif current_temp <= 10:
            advice += "🧥 有点冷，建议穿件外套出门～\n"
        elif current_temp <= 20:
            advice += "😊 温度适宜，很舒服的天气呢～\n"
        elif current_temp <= 30:
            advice += "☀️ 天气挺暖和的，适合出门活动～\n"
        else:
            advice += "🌡️ 天气很热，记得多喝水和防晒哦～\n"
        
        # 根据天气类型给出建议
        if "雨" in current_text:
            advice += "☔ 有雨哦，出门记得带伞～\n"
        elif "雪" in current_text:
            advice += "❄️ 下雪了，路面可能湿滑，小心出行～\n"
        elif "雾" in current_text:
            advice += "🌫️ 有雾，开车出行请注意安全～\n"
        elif "风" in current_text:
            advice += "💨 风比较大，注意保暖和安全～\n"
        elif "晴" in current_text:
            advice += "🌞 晴朗的好天气，心情也会很好呢～\n"
        elif "阴" in current_text or "云" in current_text:
            advice += "☁️ 多云的天气，适合散步～\n"
        
        if weather_type == "current" and 'feelsLike' in current_weather:
            feels_like = int(current_weather.get('feelsLike', current_temp))
            temp_diff = abs(current_temp - feels_like)
            if temp_diff >= 5:
                if feels_like > current_temp:
                    advice += "🌡️ 体感温度比实际温度高，注意降温～\n"
                else:
                    advice += "🌡️ 体感温度比实际温度低，注意保暖～\n"
        
        if weather_type == "hourly" and next_few_hours:
            upcoming_weathers = [item['text'] for item in next_few_hours[1:]]
            upcoming_temps = [int(item['temp']) for item in next_few_hours[1:]]
            
            if max(upcoming_temps) - min(upcoming_temps) > 5:
                advice += "🌡️ 今天温度变化较大，注意适时增减衣物～\n"
            
            if any("雨" in w for w in upcoming_weathers) and "雨" not in current_text:
                advice += "🌧️ 稍后可能有雨，记得带伞～\n"
        
        advice += "\n愿你有美好的一天！ (◡ ‿ ◡) ✨"
        return advice
    
        
    async def extract_precise_location_from_message(self, message):
        """从消息中提取更精确的地名，包括区县级别"""
        try:
            client = OpenAI(
                api_key=self.dashscope_api_key, 
                base_url=self.ai_base_url,
            )
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': '从用户消息中提取最完整的地名。如果用户说"我在嘉兴南湖区工作"，回复"嘉兴南湖区"；如果说"我在北京朝阳区"，回复"北京朝阳区"；如果只说"我在杭州"，回复"杭州"。提取最详细的地名信息，如果没有地名就回复"无"。'},
                    {'role': 'user', 'content': f'消息内容：{message}'}
                ]
            )
            precise_location = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            self.log_debug(f"从消息中提取精确地名: {precise_location}")
            return precise_location
            
        except Exception as e:
            self.log_error(f"精确地名提取失败: {e}")
            return "无"
    
    async def is_direct_location_query(self, user_input):
        """判断用户是否在直接询问特定地点的天气"""
        try:
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': '判断用户是否在明确询问特定地点的天气。如果用户明确提到某个地名并询问该地天气（如"北京天气怎么样"、"哈尔滨热不热"、"上海下雨了吗"、"铁岭市的天气"等），回复"是"；如果只是一般性询问天气（如"天气怎么样"、"今天热吗"等），回复"否"。'},
                    {'role': 'user', 'content': user_input}
                ]
            )
            
            result = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            self.log_debug(f"直接地点查询判断: {result}")
            return result == "是"
            
        except Exception as e:
            self.log_error(f"直接地点查询判断失败: {e}")
            return False
    
    async def extract_direct_location_from_query(self, user_input):
        """从直接地点查询中提取地名"""
        try:
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': '从用户明确的地点天气查询中提取地名。例如："北京天气怎么样"提取"北京"，"哈尔滨热不热"提取"哈尔滨"，"上海的天气"提取"上海"。只返回地名，不要其他内容。'},
                    {'role': 'user', 'content': user_input}
                ]
            )
            
            location = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            self.log_debug(f"从直接查询提取地名: {location}")
            return location
            
        except Exception as e:
            self.log_error(f"直接地名提取失败: {e}")
            return "无"

    async def check_and_update_user_location(self, user_id, user_input, extracted_location, current_confirmed_location):
        """检查并更新用户确认位置"""
        try:
            # 检查用户是否明确表示自己在某个地方
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': '判断用户是否在表达自己现在所在的位置。如果用户明确说自己在某地（如"我在北京"、"我现在在上海"、"我搬到杭州了"、"我在嘉兴工作"等），回复"是"；如果只是询问某地天气，回复"否"。'},
                    {'role': 'user', 'content': user_input}
                ]
            )
            
            is_location_declaration = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip() == "是"
            
            if is_location_declaration and extracted_location != "无" and extracted_location != "ask_location":
                # 用户明确表示自己的位置，更新确认位置
                if extracted_location != current_confirmed_location:
                    self.update_user_confirmed_location(user_id, extracted_location, "manual")
                    self.log_debug(f"用户明确表示位置变更: {current_confirmed_location} -> {extracted_location}")
                else:
                    self.log_debug(f"用户重新确认当前位置: {extracted_location}")
            
        except Exception as e:
            self.log_error(f"检查用户位置声明失败: {e}")

    async def extract_location_from_input_and_context(self, user_input, context, user_id=None):
        """统一的地名提取逻辑，优先判断是否为直接地点查询"""
        self.log_debug(f"开始智能地名提取和位置判断，用户输入: {user_input}")
        
        # 首先判断是否为直接地点查询
        is_direct = await self.is_direct_location_query(user_input)
        direct_query_location = None
        if is_direct:
            self.log_debug("检测到直接地点查询，提取指定地名")
            direct_location = await self.extract_direct_location_from_query(user_input)
            if direct_location != "无":
                self.log_debug(f"直接查询地名: {direct_location}")
                direct_query_location = direct_location
                # 继续检查用户位置，不直接返回
        
        # 分析用户历史位置（无论是否为直接查询都要检查）
        self.log_debug("分析用户历史位置，检查是否需要更新用户确认位置")
        # 获取用户确认位置
        user_confirmed_location = context.get('user_actual_location')
        
        # 检查历史上下文中是否有已确认的用户位置
        ai_context = context.get('ai_context', {})
        location_contexts = ai_context.get('location_contexts', [])
        
        detected_user_location = None
        if location_contexts:
            self.log_debug(f"发现历史上下文中有 {len(location_contexts)} 个地名")
            
            # 对每个地名进行位置判断，寻找用户的当前位置
            user_location_candidates = []
            
            for loc_context in location_contexts:
                location = loc_context['location']
                content = loc_context['content']
                role = loc_context['role']
                
                self.log_debug(f"分析历史地名: {location}, 角色: {role}")
                self.log_debug(f"  完整消息: {repr(content)[:80]}")
                
                # 跳过AI的回复，只分析用户的消息
                if role == 'assistant':
                    self.log_debug(f"  跳过AI回复中的地名: {location}")
                    continue
                
                # 使用AI判断这个句子是否表示用户所在位置
                self.log_debug(f"  使用AI判断地名 '{location}' 是否为用户位置")
                self.log_debug(f"  完整消息: {repr(content)}")
                
                try:
                    client = OpenAI(
                        api_key=self.dashscope_api_key,
                        base_url=self.ai_base_url,
                    )
                    
                    completion = client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {'role': 'system', 'content': '判断用户消息中提到的地名是否表示用户当前或最近的所在位置。如果是用户位置（类似一下:"我在北京"、"我现在在嘉兴南湖区"、"我还在嘉兴南湖区工作"、"我最近在上海出差"、"在嘉兴租房"、"准备在这边发展"等只要表现有疑似在这个地名的位置），就回复"是"；如果只是单纯提及一下不是用户位置（如"北京天气怎么样"、"你在哪里"等），回复"否"。重点：只要消息暗示用户在该地点生活、工作、居住或停留，就应该回复"是"。'},
                            {'role': 'user', 'content': f'消息：{content}\n地名：{location}'}
                        ]
                    )
                    ai_judgment = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
                    self.log_debug(f"  AI判断结果: {ai_judgment}")
                    
                    is_user_location = (ai_judgment == "是")
                    
                except Exception as e:
                    self.log_error(f"  AI位置判断失败: {e}")
                    is_user_location = False
                
                if is_user_location:
                    # 从完整消息中提取更精确的地名
                    precise_location = await self.extract_precise_location_from_message(content)
                    final_location = precise_location if precise_location != "无" else location
                    
                    self.log_debug(f"  ✓ 发现用户位置关键词")
                    self.log_debug(f"    - 原始地名: {location}")
                    self.log_debug(f"    - 精确地名: {precise_location}")
                    self.log_debug(f"    - 最终位置: {final_location}")
                    user_location_candidates.append({
                        "location": final_location,
                        "content": content,
                        "confidence": "keyword_match"
                    })
            
            # 如果找到了用户位置候选，选择最新的一个
            if user_location_candidates:
                selected_candidate = user_location_candidates[-1]
                detected_user_location = selected_candidate["location"]
                self.log_debug(f"从历史上下文确定用户位置: {detected_user_location}")
                self.log_debug(f"基于消息: {repr(selected_candidate['content'])[:80]}")
                
                # 自动更新用户确认位置
                if user_id and detected_user_location != user_confirmed_location:
                    self.update_user_confirmed_location(user_id, detected_user_location, "auto_detected")
                    self.log_info(f"自动更新用户确认位置: {user_confirmed_location} -> {detected_user_location}")
        
        # 如果有直接查询地点，返回它
        if direct_query_location:
            return direct_query_location
        
        # 如果历史中检测到了用户位置但没有直接查询地点，返回用户位置
        if detected_user_location and not direct_query_location:
            return detected_user_location
        
        # 如果历史中没有明确的用户位置，尝试从当前输入中提取
        if not direct_query_location:
            self.log_debug("历史上下文中未找到确认的用户位置，分析当前输入")
            try:
                client = OpenAI(
                    api_key=self.dashscope_api_key, 
                    base_url=self.ai_base_url,
                )
                
                completion = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {'role': 'system', 'content': '你需要提取用户输入中的地区名。如果用户明确提到地名（如"北京天气"、"杭州怎么样"），就回复地名；如果用户只是询问天气但没有具体地名（如"天气怎么样"、"查一下天气"），就回复"无"。'},
                        {'role': 'user', 'content': user_input}
                    ]
                )
                current_location = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"]
                self.log_debug(f"从当前输入提取地名: {current_location}")
                
                if current_location != "无":
                    return current_location
                    
            except Exception as e:
                self.log_error(f"AI地名提取失败: {e}")
            
            # 都没有找到，检查是否有用户确认位置作为默认值
            if user_confirmed_location and user_confirmed_location != "未知":
                self.log_debug(f"使用用户确认位置作为默认查询地点: {user_confirmed_location}")
                return user_confirmed_location
            
            # 都没有找到，需要询问用户
            self.log_debug("当前输入和历史上下文都未找到有效地名，需要询问用户")
            return "ask_location"

    async def get_weather_current_data(self, location_name):
        """获取实时天气数据的统一方法"""
        self.log_debug(f"开始获取实时天气数据: {location_name}")
        
        # 获取地理位置信息
        location_info = await self.get_location_info(location_name)
        if not location_info:
            return None
            
        location_id, display_location = location_info
        self.log_debug(f"获取到位置ID: {location_id}, 显示位置: {display_location}")
        
        # 获取实时天气
        url = f"https://{self.qweather_api_base_url}/v7/weather/now"
        params = {"key": self.qweather_api_key, "location": location_id}
        headers = {"Accept-Encoding": "gzip, deflate, br"}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            self.log_debug(f"实时天气API响应状态码: {response.status_code}")
            response.raise_for_status()  # 如果状态码不是2xx，则引发异常
            
            weather_data = response.json()
            if "now" not in weather_data:
                self.log_error(f"实时天气数据格式异常: {weather_data}")
                return None
            
            now_data = weather_data["now"]
            self.log_debug(f"成功获取实时天气数据: {now_data['text']} {now_data['temp']}°C")
            self.log_debug(f"天气查询日志:{display_location} 实时温度: {now_data['temp']}°C, 天气: {now_data['text']}")
            
            return {
                "location": display_location, 
                "current": now_data,
                "type": "current"
            }
        except requests.exceptions.RequestException as e:
            self.log_error(f"实时天气API请求失败: {e}")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            self.log_error(f"实时天气数据解析失败: {e}")
            return None

    async def get_weather_hourly_data(self, location_name, max_terms: int = 12):
        """获取小时天气数据的统一方法"""
        self.log_debug(f"开始获取小时天气数据: {location_name}, 时间范围: {max_terms}小时")
        
        # 获取地理位置信息
        location_info = await self.get_location_info(location_name)
        if not location_info:
            return None
            
        location_id, display_location = location_info
        self.log_debug(f"获取到位置ID: {location_id}, 显示位置: {display_location}")
        
        # 根据时间范围选择API
        if max_terms <= 24:
            url = f"https://{self.qweather_api_base_url}/v7/weather/24h"
        elif max_terms <= 72:
            url = f"https://{self.qweather_api_base_url}/v7/weather/72h"
        elif max_terms <= 168:
            url = f"https://{self.qweather_api_base_url}/v7/weather/168h"
        else:
            url = f"https://{self.qweather_api_base_url}/v7/weather/24h"
            max_terms = 24
        
        self.log_debug(f"使用天气API: {url}")
        headers = {"Accept-Encoding": "gzip, deflate, br"}
        params = {"key": self.qweather_api_key, "location": location_id}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            self.log_debug(f"天气API响应: {response.status_code}")
        except Exception as e:
            self.log_error(f"天气API请求失败: {e}")
            return None

        if response.status_code == 200:
            try:
                weather_data = response.json()
                if "hourly" not in weather_data:
                    self.log_error(f"天气数据格式异常: {weather_data}")
                    return None
                
                hourly_data = weather_data["hourly"][:max_terms]
                self.log_debug(f"成功获取天气数据，共 {len(hourly_data)} 小时")
                
                # 记录天气概况
                weather_summary = [item['text'] for item in hourly_data[:3]]
                temp_summary = [item['temp'] for item in hourly_data[:3]]
                self.log_debug(f"天气概况(前3小时): {list(zip(weather_summary, temp_summary))}")
                self.log_debug(f"【天气查询日志】{display_location} 12小时温度变化: {[item['temp'] + '°C' for item in hourly_data]}")
                
                return {"location": display_location, "hourly": hourly_data, "type": "hourly"}
            except Exception as e:
                self.log_error(f"天气数据解析失败: {e}")
                return None
        else:
            self.log_error(f"天气API调用失败，状态码: {response.status_code}")
            self.log_error(f"响应内容: {response.text[:200]}...")
            return None

    async def get_location_info(self, location_name):
        """获取地理位置信息的统一方法"""
        self.log_debug(f"查询地理位置: {location_name}")
        
        url = f"https://{self.qweather_api_base_url}/geo/v2/city/lookup"
        headers = {
            "X-QW-Api-Key": self.qweather_api_key,
            "Accept-Encoding": "gzip, deflate, br",
        }
        params = {
            "type": "scenic",
            "location": location_name
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            self.log_debug(f"地理位置API响应: {response.status_code}")
        except Exception as e:
            self.log_error(f"地理位置API请求失败: {e}")
            return None

        if response.status_code == 200:
            try:
                response_data = response.json()
                if "location" not in response_data or len(response_data["location"]) == 0:
                    self.log_info(f"未找到地名 '{location_name}' 的位置信息")
                    return None
                
                loc_data = response_data["location"][0]
                country = loc_data["country"]
                adm1 = loc_data["adm1"] 
                adm2 = loc_data["adm2"]
                name = loc_data["name"]
                location_id = loc_data["id"]
                
                self.log_debug(f"地理信息 - 国家:{country}, 省:{adm1}, 市:{adm2}, 区:{name}, ID:{location_id}")
                
                # 使用用户输入的地名作为显示名称，保持查询的一致性
                # 如果用户查询"萧山"，就显示"萧山"而不是"杭州市萧山区"
                display_location = location_name
                
                # 记录API返回的详细信息用于调试
                if country == "中国":
                    if adm2 == name:
                        api_location = adm1 + adm2 + "市"
                    else:
                        api_location = adm1 + adm2 + "市" + name + "区"
                else:
                    api_location = f"{country} {adm1} {adm2} {name}".strip()
                
                self.log_debug(f"API位置信息: {api_location}")
                self.log_debug(f"用户查询地名: {display_location}")
                return location_id, display_location
                
            except Exception as e:
                self.log_error(f"地理位置数据解析失败: {e}")
                return None
        else:
            self.log_error(f"地理位置API失败，状态码: {response.status_code}")
            return None

    async def generate_ask_location_message(self, context):
        """生成询问位置的消息"""
        try:
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            system_prompt = """你是用户的贴心朋友，用户想查天气但没有说具体地点，你需要表达自己不知道位置的困扰。

核心要求：
1. 用自然的对话语气，像朋友间聊天，不要像客服或助手
2. 语气要和回答天气建议时保持一致（温暖、关心、可爱）
3. 表达自己不知道用户在哪里的困扰，而不是反问用户
4. 适当使用颜文字表达关心（不要用emoji表情）
5. 简洁自然，不要啰嗦

回复风格：
✅ "我还不知道你在哪个城市哎 (◍•ᴗ•◍)"
✅ "唔...我不知道你的位置呢，你在哪里呀？"
✅ "我这边不知道你在哪个城市哦～"

重点：表达不知道位置的困扰，自然对话。"""
            
            context_message = "用户想查天气但没有提到具体地点。"
            if context:
                context_message += f" 当前时间{context['current_time']}，"
                context_message += f"{'工作日' if context['is_weekday'] else '周末'}。"
                context_message += f" 用户消息：'{context['user_message']}'。"
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': context_message}
                ]
            )
            
            return json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            
        except Exception as e:
            self.log_error(f"生成询问位置消息失败: {e}")
            return "我还不知道你在哪个城市哎 (◍•ᴗ•◍)"

    async def generate_chart_description(self, location, hours_count, user_input=""):
        """生成动态的图表描述"""
        try:
            client = OpenAI(
                api_key=self.dashscope_api_key,
                base_url=self.ai_base_url,
            )
            
            system_prompt = """你是用户的贴心朋友，刚刚为ta生成了天气趋势图，现在要告诉ta图表已经准备好了。

核心要求：
1. 用朋友的语气，温暖自然，不要像助手或AI
2. 根据实际的小时数来描述（6小时、12小时、24小时等）
3. 适当使用颜文字表达关心（不要用emoji表情）
4. 简洁可爱，一句话即可
5. 避免使用"这是"、"为您"、"请查看"等正式用语

时间描述要求：
- 如果是6小时：说成"接下来6小时"或"未来6小时"
- 如果是12小时：说成"接下来12小时"或"未来12小时"  
- 如果是24小时：说成"未来一天"或"明天一整天"

回复风格示例：
✅ "给你做了个哈尔滨接下来6小时的天气图哦 (｡･ω･｡)ﾉ"
✅ "北京未来12小时的天气趋势图出炉啦～ (◍•ᴗ•◍)"
✅ "上海明天一整天的天气情况看这里呀 ♡(>ᴗ•)"

重点：朋友语气，根据实际小时数描述，温暖可爱。"""
            
            time_desc = f"{hours_count}小时"
            if hours_count == 24:
                time_desc = "一天"
            elif hours_count >= 48:
                time_desc = f"{hours_count//24}天"
            
            context_message = f"刚刚为用户生成了{location}未来{time_desc}的天气趋势图，现在要告诉用户图表准备好了。"
            if user_input:
                context_message += f" 用户原始询问：'{user_input}'。"
            
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': context_message}
                ]
            )
            
            return json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            
        except Exception as e:
            self.log_error(f"生成图表描述失败: {e}")
            # 降级方案
            if hours_count == 6:
                return f"给你做了个{location}接下来6小时的天气图哦 (｡･ω･｡)ﾉ"
            elif hours_count == 12:
                return f"{location}未来12小时的天气趋势图出炉啦～ (◍•ᴗ•◍)"
            elif hours_count == 24:
                return f"{location}明天一整天的天气情况看这里呀 ♡(>ᴗ•)"
            else:
                return f"{location}未来{hours_count}小时的天气图给你准备好了 (｡･ω･｡)ﾉ"

    async def _need_detailed_chart(self, user_input):
        """判断用户是否需要详细的天气图表"""
        self.log_debug(f"判断用户是否需要详细图表: {user_input}")
        
        # 关键词匹配
        detailed_keywords = [
            "图", "图表", "图片", "图像", "图示", "详细", "趋势", "曲线", 
            "走势", "变化", "12小时", "一天", "24小时", "小时天气"
        ]
        if any(keyword in user_input.lower() for keyword in detailed_keywords):
            self.log_debug(f"检测到详细图表关键词")
            return True
        
        # AI判断
        try:
            client = OpenAI(api_key=self.dashscope_api_key, base_url=self.ai_base_url)
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': '判断用户是否需要详细的天气图表/图片。如果用户想要详细的天气趋势、图表、图片、12小时天气变化等，回复"是"；如果只是简单询问天气情况，回复"否"。'},
                    {'role': 'user', 'content': user_input}
                ]
            )
            ai_response = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
            self.log_debug(f"AI判断图表需求结果: {ai_response}")
            return ai_response == "是"
        except Exception as e:
            self.log_error(f"AI判断图表需求失败: {e}")
            return False

    def _determine_weather_api_type(self, user_input):
        """智能判断应该使用哪种天气API"""
        self.log_debug(f"判断天气API类型: {user_input}")
        
        # 实时天气关键词
        if any(keyword in user_input.lower() for keyword in ["现在", "当前", "此刻", "目前", "实时", "今天天气", "今日天气"]):
            self.log_debug(f"检测到实时天气关键词")
            return "current"
        
        # 小时预报关键词
        if any(keyword in user_input.lower() for keyword in ["小时", "趋势", "变化", "未来", "今天详细", "24小时", "12小时"]):
            self.log_debug(f"检测到小时预报关键词")
            return "hourly"
        
        self.log_debug("未检测到特定关键词，默认使用实时天气API")
        return "current"

    async def _generate_simple_weather_reply(self, data, event_obj, user_input=""):
        """生成简洁的天气回复，只包含健康建议"""
        if data.get('type') == 'current':
            current_weather = data['current']
            return await self.get_weather_advice_current(current_weather, event_obj, data['location'], user_input)
        else:
            current_weather = data['hourly'][0]
            next_few_hours = data['hourly'][:6]
            return await self.get_weather_advice(current_weather, next_few_hours, event_obj, data['location'], user_input)

    def _load_weather_icon(self, text, plugin_dir):
        """加载天气图标并适配大小"""
        weather_icons = {
            '晴': os.path.join(plugin_dir, "icons", "sunny.png"), '雨': os.path.join(plugin_dir, "icons", "rainy.png"),
            '大雨': os.path.join(plugin_dir, "icons", "rainy.png"), '小雨': os.path.join(plugin_dir, "icons", "rainy.png"),
            '中雨': os.path.join(plugin_dir, "icons", "rainy.png"), '多云': os.path.join(plugin_dir, "icons", "partly_cloudy.png"),
            '局部多云': os.path.join(plugin_dir, "icons", "partly_cloudy.png"), '大部多云': os.path.join(plugin_dir, "icons", "partly_cloudy.png"),
            '雪': os.path.join(plugin_dir, "icons", "snowy.png"), '大雪': os.path.join(plugin_dir, "icons", "snowy.png"),
            '小雪': os.path.join(plugin_dir, "icons", "snowy.png"), '中雪': os.path.join(plugin_dir, "icons", "snowy.png"),
            '阴': os.path.join(plugin_dir, "icons", "cloudy.png"), '风': os.path.join(plugin_dir, "icons", "windy.png"),
            '大风': os.path.join(plugin_dir, "icons", "windy.png"), '雾': os.path.join(plugin_dir, "icons", "foggy.png"),
            '大雾': os.path.join(plugin_dir, "icons", "foggy.png"),
        }
        icon_path = weather_icons.get(text, os.path.join(plugin_dir, "icons", "not_supported.png"))
        return OffsetImage(plt.imread(icon_path), zoom=0.2)

    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        msg = event.get_message_str()
        self.log_info(f"天气插件收到消息: {msg}")

        # 检查是否是天气查询
        is_weather_query = False
        if msg.startswith(tuple(self.wake_msg)):
            self.log_info("通过触发词触发天气查询")
            is_weather_query = True
        else:
            self.log_debug("开始AI判断是否为天气询问")
            client = OpenAI(api_key=self.dashscope_api_key, base_url=self.ai_base_url)
            try:
                completion = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {'role': 'system', 'content': '判断用户是否在询问天气信息。如果是询问天气，回复"是"，否则回复"否".'},
                        {'role': 'user', 'content': msg}
                    ]
                )
                ai_response = json.loads(completion.model_dump_json())["choices"][0]["message"]["content"].strip()
                self.log_debug(f"AI判断结果: {ai_response}")
                if ai_response == "是":
                    is_weather_query = True
                    self.log_info("AI判断是天气询问，触发天气查询功能")
                else:
                    self.log_debug("AI判断不是天气询问，跳过处理")
            except Exception as e:
                self.log_error(f"AI判断API调用失败: {e}")
                return

        if not is_weather_query:
            return

        self.log_info("开始处理天气查询流程")

        # 获取用户ID和确认位置
        user_id = getattr(event, 'unified_msg_origin', 'unknown')
        user_confirmed_location = self.get_user_confirmed_location(user_id)
        self.log_debug(f"用户 {user_id} 的确认位置: {user_confirmed_location}")
        
        # 先进行基础的上下文分析
        self.log_debug("分析用户上下文")
        initial_context = await self.analyze_user_context(event, "", user_confirmed_location)
        
        # 提取地名
        self.log_info("智能提取地名", console=False)
        location_name = await self.extract_location_from_input_and_context(msg, initial_context, user_id)
        
        # 检查是否需要更新用户确认位置
        await self.check_and_update_user_location(user_id, msg, location_name, user_confirmed_location)
        
        # 如果没有地名，询问用户
        if location_name == "ask_location":
            self.log_info("未找到地名，询问用户位置")
            ask_message = await self.generate_ask_location_message(initial_context)
            yield event.chain_result([Plain(ask_message)])
            return
        
        self.log_info(f"确定查询地点: {location_name}")

        # 判断用户需求类型
        self.log_debug("判断用户需求类型")
        needs_chart = await self._need_detailed_chart(msg)
        
        # 获取天气数据
        self.log_debug("根据需求获取天气数据")
        data = None
        if needs_chart:
            self.log_info("用户需要图表，获取小时天气数据")
            data = await self.get_weather_hourly_data(location_name, 12)
        else:
            api_type = self._determine_weather_api_type(msg)
            self.log_debug(f"用户需要简单回复，判断API类型: {api_type}")
            if api_type == "current":
                data = await self.get_weather_current_data(location_name)
            else:
                data = await self.get_weather_hourly_data(location_name, 12)

        if not data:
            self.log_error("未能获取到任何天气数据，处理中止")
            yield event.chain_result([Plain("抱歉，查询天气失败了 (´;ω;`)")])
            return

        # 生成并发送回复
        self.log_debug("生成并发送最终回复")
        
        if needs_chart and (data.get('type') == 'current' or len(data.get('hourly', [])) < 6):
            self.log_info("需要图表但条件不足，降级为简单文字回复")
            needs_chart = False

        if not needs_chart:
            self.log_info("生成简单文字回复")
            weather_reply = await self._generate_simple_weather_reply(data, event, msg)
            yield event.chain_result([Plain(weather_reply)])
            return
        
        # 生成图片
        self.log_info("用户需要详细图表，开始生成图片")
        
        hourly_data = data.get('hourly', [])
        hours = [datetime.fromisoformat(item['fxTime']).strftime('%H:%M') for item in hourly_data]
        temps = [float(item['temp']) for item in hourly_data]
        weather_texts = [item['text'] for item in hourly_data]
        location = data['location']

        x = np.arange(len(temps))
        y = np.array(temps)
        x_new = np.linspace(x.min(), x.max(), 300)
        spl = make_interp_spline(x, y, k=3)
        y_smooth = spl(x_new)

        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        font_path = os.path.join(plugin_dir, "SourceHanSansCN-Regular.otf")
        prop = fm.FontProperties(fname=font_path, size=12)

        fig, ax = plt.subplots(figsize=(16, 9), facecolor='#F5F5F5')
        ax.plot(x_new, y_smooth, color='#E74C3C', linewidth=2, zorder=10)
        ax.set_xticks(x)
        ax.set_xticklabels(hours, fontproperties=prop)
        ax.set_xlabel('时间', fontproperties=prop, fontsize=14)
        ax.set_ylabel('温度 (°C)', fontproperties=prop, fontsize=14)
        # 动态生成标题  
        hours_count = len(hourly_data)
        if hours_count == 24:
            time_desc = "未来一天"
        elif hours_count <= 6:
            time_desc = f"未来{hours_count}小时"
        else:
            time_desc = f"未来{hours_count}小时"
        ax.set_title(f'{location} {time_desc}天气趋势', fontproperties=prop, fontsize=20, pad=20)
        ax.grid(True, linestyle='--', alpha=0.6)

        weather_icons = {
            '晴': os.path.join(plugin_dir, "icons", "sunny.png"), '雨': os.path.join(plugin_dir, "icons", "rainy.png"),
            '大雨': os.path.join(plugin_dir, "icons", "rainy.png"), '小雨': os.path.join(plugin_dir, "icons", "rainy.png"),
            '中雨': os.path.join(plugin_dir, "icons", "rainy.png"), '多云': os.path.join(plugin_dir, "icons", "partly_cloudy.png"),
            '局部多云': os.path.join(plugin_dir, "icons", "partly_cloudy.png"), '大部多云': os.path.join(plugin_dir, "icons", "partly_cloudy.png"),
            '雪': os.path.join(plugin_dir, "icons", "snowy.png"), '大雪': os.path.join(plugin_dir, "icons", "snowy.png"),
            '小雪': os.path.join(plugin_dir, "icons", "snowy.png"), '中雪': os.path.join(plugin_dir, "icons", "snowy.png"),
            '阴': os.path.join(plugin_dir, "icons", "cloudy.png"), '风': os.path.join(plugin_dir, "icons", "windy.png"),
            '大风': os.path.join(plugin_dir, "icons", "windy.png"), '雾': os.path.join(plugin_dir, "icons", "foggy.png"),
            '大雾': os.path.join(plugin_dir, "icons", "foggy.png"),
        }

        def load_weather_icon(text):
            icon_path = weather_icons.get(text, os.path.join(plugin_dir, "icons", "not_supported.png"))
            return OffsetImage(plt.imread(icon_path), zoom=0.2)

        for xi, yi, text in zip(x, temps, weather_texts):
            y_offset = (max(temps) - min(temps)) * 0.15 if max(temps) != min(temps) else 10
            offset_sign = 1 if yi < np.median(temps) else -1
            ab = AnnotationBbox(self._load_weather_icon(text, plugin_dir), (xi, yi),
                                xycoords='data', xybox=(0, y_offset * offset_sign * -1),
                                boxcoords="offset points", box_alignment=(0.5, 0.5),
                                frameon=False, zorder=20)
            ax.add_artist(ab)
            ax.text(xi, yi + 0.3, f'{yi}°', ha='center', va='bottom', fontproperties=prop, color='#2C3E50', fontsize=16, zorder=30)

        plt.subplots_adjust(bottom=0.15)
        
        session_id = event.unified_msg_origin.replace(":", "")
        img_path_png = os.path.join(plugin_dir, f"{session_id}_weather.png")
        img_path_jpg = os.path.join(plugin_dir, f"{session_id}_weather.jpg")
        plt.savefig(img_path_png, dpi=300, bbox_inches='tight')
        plt.close()

        ImageW.open(img_path_png).convert('RGB').save(img_path_jpg, quality=95)
        
        current_weather = data['hourly'][0]
        next_few_hours = data['hourly'][:6]
        weather_advice = await self.get_weather_advice(current_weather, next_few_hours, event, data['location'], msg)
        
        # 动态生成图表描述
        chart_description = await self.generate_chart_description(location, len(hourly_data), msg)

        chain = [
            Plain(weather_advice + f"\n{chart_description}"),
            Image.fromFileSystem(img_path_jpg),
        ]
        yield event.chain_result(chain)

        os.remove(img_path_png)
        os.remove(img_path_jpg)
        
