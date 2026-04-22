"""
个性一致性测试脚本

这个脚本用于验证 vir-bot 的人设一致性。测试内容包括：
1. 重复问题一致性 - 问同一个问题多次，检查答案的一致度
2. 人设遵守 - 验证 AI 是否表现出设定的性格特点
3. 记忆准确性 - 验证是否能从 Wiki 和 RAG 中准确检索信息
4. 禁忌遵守 - 验证是否避免禁止的行为
5. 喜好识别 - 验证是否识别并响应个人喜好

使用方式：
    python test_personality_consistency.py

或者运行特定测试：
    python test_personality_consistency.py --test consistency
    python test_personality_consistency.py --test taboo
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from vir_bot.config import load_config
from vir_bot.core.ai_provider import AIProviderFactory
from vir_bot.core.memory import LongTermMemory, MemoryManager, ShortTermMemory
from vir_bot.core.wiki import WikiKnowledgeBase
from vir_bot.utils.logger import logger, setup_logger


class PersonalityConsistencyTester:
    """个性一致性测试器"""

    def __init__(self, character_name: str = "xiaoya"):
        self.character_name = character_name
        self.config = None
        self.ai_provider = None
        self.memory_manager = None
        self.wiki = None
        self.character_profile = None
        self.test_results = {}

    async def setup(self):
        """初始化测试环境"""
        print("\n" + "=" * 70)
        print("初始化测试环境")
        print("=" * 70)

        # 加载配置
        self.config = load_config()
        print(f"✓ 配置已加载")

        # 初始化 AI Provider
        self.ai_provider = AIProviderFactory.create(self.config.ai)
        health = await self.ai_provider.health_check()
        if not health:
            print(f"❌ AI Provider 不健康: {self.config.ai.provider}")
            return False
        print(f"✓ AI Provider 就绪: {self.config.ai.provider}")

        # 初始化内存系统
        short_term = ShortTermMemory(max_turns=self.config.memory.short_term.max_turns)
        long_term = (
            LongTermMemory(
                persist_dir=self.config.memory.long_term.persist_dir,
                collection_name=self.config.memory.long_term.collection_name,
                embedding_model=self.config.memory.long_term.embedding_model,
                top_k=self.config.memory.long_term.top_k,
            )
            if self.config.memory.long_term.enabled
            else None
        )

        self.memory_manager = MemoryManager(
            short_term=short_term,
            long_term=long_term,
            window_size=self.config.memory.short_term.window_size,
        )
        print(f"✓ 内存系统就绪")

        # 加载 Wiki
        self.wiki = WikiKnowledgeBase()
        self.character_profile = await self.wiki.load_character(self.character_name)
        if not self.character_profile:
            print(f"❌ 角色未找到: {self.character_name}")
            return False
        print(f"✓ 角色已加载: {self.character_name}")

        # 设置当前角色
        await self.memory_manager.set_character(self.character_name)
        print(f"✓ 内存管理器已初始化")

        return True

    async def test_consistency(self, num_iterations: int = 5):
        """测试一致性 - 问同一个问题多次"""
        print("\n" + "=" * 70)
        print("测试 1: 个性一致性")
        print("=" * 70)

        questions = [
            "你好，自我介绍一下",
            "你叫什么名字",
            "你的性格是什么样的",
            "你喜欢什么",
            "你讨厌什么",
        ]

        consistency_scores = {}

        for question in questions:
            print(f"\n📝 问题: {question}")
            print(f"重复 {num_iterations} 次...")

            responses = []
            for i in range(num_iterations):
                try:
                    system_prompt = await self.memory_manager.build_enhanced_system_prompt(
                        current_query=question,
                        base_system_prompt="你是一个有帮助的助手",
                        character_name=self.character_name,
                    )

                    response = await self.ai_provider.chat(
                        messages=[{"role": "user", "content": question}],
                        system=system_prompt,
                    )
                    responses.append(response.content)
                    print(f"  [{i + 1}/{num_iterations}] ✓")
                except Exception as e:
                    print(f"  [{i + 1}/{num_iterations}] ❌ {e}")
                    responses.append("")

            # 计算相似度
            if responses and all(responses):
                similarity = self._calculate_similarity(responses)
                consistency_scores[question] = similarity
                print(f"\n  一致度: {similarity:.1%}")

                if similarity >= 0.8:
                    print(f"  ✅ 通过 (>= 80%)")
                elif similarity >= 0.6:
                    print(f"  ⚠️ 警告 (60-80%)")
                else:
                    print(f"  ❌ 失败 (< 60%)")

                # 显示样本回复
                print(f"\n  样本回复 (第1次):")
                print(f"  {responses[0][:150]}...")

        self.test_results["consistency"] = consistency_scores
        avg_score = (
            sum(consistency_scores.values()) / len(consistency_scores) if consistency_scores else 0
        )
        print(f"\n平均一致度: {avg_score:.1%}")

        return avg_score >= 0.8

    async def test_personality_traits(self):
        """测试人设特征 - 验证是否表现出设定的性格"""
        print("\n" + "=" * 70)
        print("测试 2: 人设特征识别")
        print("=" * 70)

        if not self.character_profile:
            print("❌ 角色配置未加载")
            return False

        traits = self.character_profile.personality_traits
        print(f"\n检查人设特征: {len(traits)} 个")

        trait_tests = {}

        for trait in traits[:3]:  # 只测试前3个特征
            print(f"\n🎭 特征: {trait.name}")
            print(f"描述: {trait.description}")

            # 构造问题来触发这个特征
            test_question = f"请展现你的'{trait.name}'特点"

            try:
                system_prompt = await self.memory_manager.build_enhanced_system_prompt(
                    current_query=test_question,
                    base_system_prompt="",
                    character_name=self.character_name,
                )

                response = await self.ai_provider.chat(
                    messages=[{"role": "user", "content": test_question}],
                    system=system_prompt,
                )

                # 简单的启发式检查
                trait_detected = self._check_trait_presence(trait.name, response.content)

                if trait_detected:
                    print(f"✅ 检测到特征")
                    trait_tests[trait.name] = True
                else:
                    print(f"⚠️ 未明确检测到特征")
                    trait_tests[trait.name] = False

            except Exception as e:
                print(f"❌ 错误: {e}")
                trait_tests[trait.name] = False

        self.test_results["personality_traits"] = trait_tests
        pass_count = sum(1 for v in trait_tests.values() if v)
        print(f"\n人设特征识别: {pass_count}/{len(trait_tests)} 通过")

        return pass_count >= len(trait_tests) * 0.7

    async def test_preferences(self):
        """测试喜好识别"""
        print("\n" + "=" * 70)
        print("测试 3: 个人喜好识别")
        print("=" * 70)

        if not self.character_profile or not self.character_profile.preferences:
            print("❌ 未找到个人喜好定义")
            return False

        prefs = self.character_profile.preferences
        print(f"\n检查喜好: {len(prefs)} 个")

        preference_tests = {}

        for pref in prefs[:3]:  # 只测试前3个
            print(f"\n❤️ 喜好: {pref.name}")
            print(f"描述: {pref.description}")

            test_question = f"你喜欢{pref.name}吗？"

            try:
                system_prompt = await self.memory_manager.build_enhanced_system_prompt(
                    current_query=test_question,
                    base_system_prompt="",
                    character_name=self.character_name,
                )

                response = await self.ai_provider.chat(
                    messages=[{"role": "user", "content": test_question}],
                    system=system_prompt,
                )

                # 检查是否承认喜好
                confirms_preference = any(
                    word in response.content for word in ["喜欢", "喜爱", "热爱", "很好"]
                )

                if confirms_preference:
                    print(f"✅ 确认喜好")
                    preference_tests[pref.name] = True
                else:
                    print(f"⚠️ 未确认喜好")
                    preference_tests[pref.name] = False

            except Exception as e:
                print(f"❌ 错误: {e}")
                preference_tests[pref.name] = False

        self.test_results["preferences"] = preference_tests
        pass_count = sum(1 for v in preference_tests.values() if v)
        print(f"\n喜好识别: {pass_count}/{len(preference_tests)} 通过")

        return pass_count >= len(preference_tests) * 0.7

    async def test_taboos(self):
        """测试禁忌遵守"""
        print("\n" + "=" * 70)
        print("测试 4: 禁忌遵守")
        print("=" * 70)

        if not self.character_profile or not self.character_profile.taboos:
            print("❌ 未找到禁忌定义")
            return False

        taboos = self.character_profile.taboos
        print(f"\n检查禁忌: {len(taboos)} 个")

        taboo_tests = {}

        for taboo in taboos[:2]:  # 只测试前2个
            print(f"\n⛔ 禁忌: {taboo.action}")
            print(f"后果: {taboo.consequence}")

            # 模拟禁忌行为
            test_question = f"我要{taboo.action}"

            try:
                system_prompt = await self.memory_manager.build_enhanced_system_prompt(
                    current_query=test_question,
                    base_system_prompt="",
                    character_name=self.character_name,
                )

                response = await self.ai_provider.chat(
                    messages=[{"role": "user", "content": test_question}],
                    system=system_prompt,
                )

                # 检查是否表现出不满
                shows_negative_reaction = any(
                    word in response.content
                    for word in ["不", "讨厌", "生气", "难受", "伤心", "呜"]
                )

                if shows_negative_reaction:
                    print(f"✅ 表现出负面反应")
                    taboo_tests[taboo.action] = True
                else:
                    print(f"⚠️ 未表现出明确的负面反应")
                    taboo_tests[taboo.action] = False

            except Exception as e:
                print(f"❌ 错误: {e}")
                taboo_tests[taboo.action] = False

        self.test_results["taboos"] = taboo_tests
        pass_count = sum(1 for v in taboo_tests.values() if v)
        print(f"\n禁忌遵守: {pass_count}/{len(taboo_tests)} 通过")

        return pass_count >= len(taboo_tests) * 0.7

    async def test_memory_recall(self):
        """测试记忆回忆"""
        print("\n" + "=" * 70)
        print("测试 5: 记忆回忆")
        print("=" * 70)

        # 添加一些测试记忆
        print("\n添加测试记忆...")
        test_memories = [
            ("用户的名字是张三", "personality", 0.8, ["张三"]),
            ("用户喜欢听歌", "preference", 0.9, ["音乐", "喜好"]),
            ("用户的生日是12月25日", "event", 0.9, ["生日", "重要日期"]),
        ]

        for content, mem_type, importance, entities in test_memories:
            await self.memory_manager.long_term.add(
                content=content,
                type=mem_type,
                importance=importance,
                entities=entities,
            )

        print(f"✓ {len(test_memories)} 条记忆已添加")

        # 测试回忆
        print("\n测试记忆回忆...")
        recall_tests = {}

        for content, mem_type, _, _ in test_memories:
            query_word = content.split("是")[1].split("的")[0] if "是" in content else content[:10]

            try:
                memories = await self.memory_manager.search_long_term(
                    query=query_word,
                    top_k=1,
                )

                if memories and mem_type in [m.type for m in memories]:
                    print(f"✅ 成功回忆: {mem_type}")
                    recall_tests[content] = True
                else:
                    print(f"⚠️ 未能准确回忆: {mem_type}")
                    recall_tests[content] = False

            except Exception as e:
                print(f"❌ 错误: {e}")
                recall_tests[content] = False

        self.test_results["memory_recall"] = recall_tests
        pass_count = sum(1 for v in recall_tests.values() if v)
        print(f"\n记忆回忆: {pass_count}/{len(recall_tests)} 通过")

        return pass_count >= len(recall_tests) * 0.7

    async def test_catch_phrases(self):
        """测试口头禅"""
        print("\n" + "=" * 70)
        print("测试 6: 口头禅使用")
        print("=" * 70)

        if not self.character_profile or not self.character_profile.catch_phrases:
            print("❌ 未找到口头禅定义")
            return False

        phrases = self.character_profile.catch_phrases
        print(f"\n检查口头禅: {len(phrases)} 个")

        phrase_tests = {}

        for phrase in phrases[:3]:  # 只测试前3个
            print(f"\n💬 口头禅: '{phrase.phrase}'")
            print(f"场景: {phrase.scenario}")

            # 构造能触发这个口头禅的问题
            test_question = f"请在这个场景中回应：{phrase.scenario}"

            try:
                system_prompt = await self.memory_manager.build_enhanced_system_prompt(
                    current_query=test_question,
                    base_system_prompt="",
                    character_name=self.character_name,
                )

                response = await self.ai_provider.chat(
                    messages=[{"role": "user", "content": test_question}],
                    system=system_prompt,
                )

                # 检查是否使用了这个口头禅
                uses_phrase = phrase.phrase in response.content

                if uses_phrase:
                    print(f"✅ 使用了口头禅")
                    phrase_tests[phrase.phrase] = True
                else:
                    print(f"⚠️ 未使用口头禅（可能是生成内容的多样性）")
                    phrase_tests[phrase.phrase] = False

            except Exception as e:
                print(f"❌ 错误: {e}")
                phrase_tests[phrase.phrase] = False

        self.test_results["catch_phrases"] = phrase_tests
        pass_count = sum(1 for v in phrase_tests.values() if v)
        print(f"\n口头禅使用: {pass_count}/{len(phrase_tests)} 通过")

        return pass_count >= len(phrase_tests) * 0.5  # 口头禅要求较低

    def _calculate_similarity(self, texts: list[str]) -> float:
        """计算文本列表的相似度（简单实现）"""
        if len(texts) < 2:
            return 1.0

        # 简单的词序列相似度
        total_similarity = 0
        comparisons = 0

        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                # 计算共同词汇的比例
                words_i = set(texts[i].split())
                words_j = set(texts[j].split())

                if words_i or words_j:
                    intersection = len(words_i & words_j)
                    union = len(words_i | words_j)
                    similarity = intersection / union if union > 0 else 0
                    total_similarity += similarity
                    comparisons += 1

        return total_similarity / comparisons if comparisons > 0 else 0

    def _check_trait_presence(self, trait_name: str, text: str) -> bool:
        """检查文本中是否包含特定特征的表现"""
        keywords = {
            "温柔体贴": ["温柔", "关心", "体贴", "照顾"],
            "活泼开朗": ["活泼", "开朗", "开心", "兴奋"],
            "会撒娇": ["撒娇", "讨厌", "哎呀", "呜"],
            "有点傲娇": ["傲娇", "讨厌", "才不是", "哼"],
        }

        trait_keywords = keywords.get(trait_name, [trait_name])
        return any(keyword in text for keyword in trait_keywords)

    async def run_all_tests(self):
        """运行所有测试"""
        print("\n")
        print("█" * 70)
        print("█  vir-bot 个性一致性综合测试")
        print("█" * 70)
        print("\n")

        if not await self.setup():
            print("\n❌ 初始化失败")
            return False

        results = []

        # 运行各个测试
        try:
            results.append(("个性一致性", await self.test_consistency(num_iterations=3)))
            results.append(("人设特征", await self.test_personality_traits()))
            results.append(("个人喜好", await self.test_preferences()))
            results.append(("禁忌遵守", await self.test_taboos()))
            results.append(("记忆回忆", await self.test_memory_recall()))
            results.append(("口头禅使用", await self.test_catch_phrases()))
        except Exception as e:
            logger.error(f"测试执行出错: {e}")
            import traceback

            traceback.print_exc()

        # 输出总结
        self._print_summary(results)

        return all(passed for _, passed in results)

    def _print_summary(self, results: list):
        """输出测试总结"""
        print("\n" + "=" * 70)
        print("测试总结")
        print("=" * 70)
        print()

        passed_count = 0
        for test_name, passed in results:
            status = "✅ 通过" if passed else "❌ 失败"
            print(f"{test_name:20} {status}")
            if passed:
                passed_count += 1

        print()
        print(
            f"总体通过率: {passed_count}/{len(results)} ({passed_count / len(results) * 100:.0f}%)"
        )

        if passed_count >= len(results) * 0.7:
            print("\n🎉 大多数测试通过！个性一致性良好。")
        else:
            print("\n⚠️ 部分测试未通过，需要调整人设卡或系统提示词。")

        # 保存结果到文件
        result_file = Path("test_results.json")
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(self.test_results, f, ensure_ascii=False, indent=2)
        print(f"\n详细结果已保存到: {result_file}")


async def main():
    """主函数"""
    setup_logger(level="INFO")

    tester = PersonalityConsistencyTester(character_name="xiaoya")
    success = await tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
