from __future__ import annotations

import os
import re
from html import unescape
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from app.models.runtime import Job


TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
BRAVE_WEB_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DUCKDUCKGO_LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"


FIRST_PARTY_SOURCE_SEEDS: tuple[dict[str, str], ...] = (
    {
        "url": "https://arxiv.org/abs/2203.02155",
        "title": "Training language models to follow instructions with human feedback",
        "notes": "InstructGPT / RLHF source for instruction tuning and reward-model-based alignment.",
        "terms": "rlhf sft instruction tuning alignment pretraining",
    },
    {
        "url": "https://arxiv.org/abs/2305.18290",
        "title": "Direct Preference Optimization: Your Language Model is Secretly a Reward Model",
        "notes": "DPO paper; contrasts direct preference optimization with RLHF-style policy optimization.",
        "terms": "dpo rlhf alignment preference optimization",
    },
    {
        "url": "https://arxiv.org/abs/2402.01306",
        "title": "KTO: Model Alignment as Prospect Theoretic Optimization",
        "notes": "KTO alignment paper; useful for comparing RLHF/DPO/KTO engineering trade-offs.",
        "terms": "kto alignment preference optimization",
    },
    {
        "url": "https://arxiv.org/abs/2106.09685",
        "title": "LoRA: Low-Rank Adaptation of Large Language Models",
        "notes": "LoRA paper; explains low-rank adaptation for parameter-efficient fine-tuning.",
        "terms": "lora peft fine tuning adapter",
    },
    {
        "url": "https://arxiv.org/abs/2305.14314",
        "title": "QLoRA: Efficient Finetuning of Quantized LLMs",
        "notes": "QLoRA paper; connects quantization with memory-efficient supervised fine-tuning.",
        "terms": "qlora lora quantization peft fine tuning",
    },
    {
        "url": "https://arxiv.org/abs/2210.17323",
        "title": "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers",
        "notes": "GPTQ post-training quantization source for deployment and accuracy/cost trade-offs.",
        "terms": "gptq quantization deployment inference",
    },
    {
        "url": "https://arxiv.org/abs/2306.00978",
        "title": "AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration",
        "notes": "AWQ quantization source for inference compression and deployment optimization.",
        "terms": "awq quantization deployment inference",
    },
    {
        "url": "https://arxiv.org/abs/2307.09288",
        "title": "Llama 2: Open Foundation and Fine-Tuned Chat Models",
        "notes": "Llama 2 paper; useful for open model comparison and alignment discussion.",
        "terms": "llama model selection open model alignment",
    },
    {
        "url": "https://arxiv.org/abs/2405.04434",
        "title": "DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model",
        "notes": "DeepSeek-V2 paper; connects architecture choices with inference cost.",
        "terms": "deepseek moe model selection inference cost",
    },
    {
        "url": "https://arxiv.org/abs/2412.19437",
        "title": "DeepSeek-V3 Technical Report",
        "notes": "DeepSeek-V3 report; useful for model selection, training, and deployment discussion.",
        "terms": "deepseek v3 model selection training inference",
    },
    {
        "url": "https://huggingface.co/docs/peft/index",
        "title": "Hugging Face PEFT documentation",
        "notes": "PEFT docs covering parameter-efficient fine-tuning methods and practical usage.",
        "terms": "peft lora adapter p-tuning ia3 fine tuning",
    },
    {
        "url": "https://huggingface.co/docs/peft/task_guides/lora_based_methods",
        "title": "Hugging Face PEFT LoRA-based methods guide",
        "notes": "Practical LoRA/PEFT method guidance for application engineers.",
        "terms": "lora peft fine tuning adapter",
    },
    {
        "url": "https://huggingface.co/docs/peft/package_reference/ia3",
        "title": "Hugging Face PEFT IA3 reference",
        "notes": "IA3 adapter reference for parameter-efficient fine-tuning comparisons.",
        "terms": "ia3 peft adapter fine tuning",
    },
    {
        "url": "https://huggingface.co/docs/peft/package_reference/prompt_tuning",
        "title": "Hugging Face PEFT prompt tuning reference",
        "notes": "Prompt tuning reference for contrasting PEFT choices.",
        "terms": "p-tuning prompt tuning peft fine tuning",
    },
    {
        "url": "https://huggingface.co/docs/transformers/quantization/overview",
        "title": "Hugging Face Transformers quantization overview",
        "notes": "Deployment-focused quantization overview covering memory and performance trade-offs.",
        "terms": "quantization deployment inference gptq awq int4 int8",
    },
    {
        "url": "https://huggingface.co/docs/transformers/perf_infer_gpu_one",
        "title": "Hugging Face Transformers single-GPU inference optimization",
        "notes": "Inference optimization guidance for latency, memory, and throughput discussions.",
        "terms": "deployment inference latency memory throughput",
    },
    {
        "url": "https://huggingface.co/docs/transformers/peft",
        "title": "Hugging Face Transformers PEFT integration",
        "notes": "Transformers-side PEFT integration guidance for training and deployment workflows.",
        "terms": "peft lora adapter fine tuning deployment",
    },
    {
        "url": "https://huggingface.co/docs/trl/dpo_trainer",
        "title": "Hugging Face TRL DPO Trainer",
        "notes": "Implementation-facing DPO trainer docs for alignment workflow discussion.",
        "terms": "dpo trl alignment trainer",
    },
    {
        "url": "https://huggingface.co/docs/trl/kto_trainer",
        "title": "Hugging Face TRL KTO Trainer",
        "notes": "Implementation-facing KTO trainer docs for alignment workflow discussion.",
        "terms": "kto trl alignment trainer",
    },
    {
        "url": "https://huggingface.co/docs/trl/sft_trainer",
        "title": "Hugging Face TRL SFT Trainer",
        "notes": "SFT trainer docs for instruction-tuning workflow and data-format discussions.",
        "terms": "sft trl instruction tuning fine tuning",
    },
    {
        "url": "https://huggingface.co/docs/bitsandbytes/index",
        "title": "Hugging Face bitsandbytes documentation",
        "notes": "Quantization and optimizer docs commonly used in low-cost LLM fine-tuning.",
        "terms": "bitsandbytes quantization qlora fine tuning",
    },
    {
        "url": "https://ai.meta.com/llama/",
        "title": "Meta Llama official page",
        "notes": "Official Llama entry point for model-family and deployment selection discussion.",
        "terms": "llama meta model selection",
    },
    {
        "url": "https://github.com/deepseek-ai/DeepSeek-V3",
        "title": "DeepSeek-V3 GitHub repository",
        "notes": "Official DeepSeek-V3 repository with model details and usage notes.",
        "terms": "deepseek v3 model selection deployment",
    },
    {
        "url": "https://github.com/deepseek-ai/DeepSeek-V2",
        "title": "DeepSeek-V2 GitHub repository",
        "notes": "Official DeepSeek-V2 repository for MoE and inference-cost discussion.",
        "terms": "deepseek v2 moe inference cost",
    },
    {
        "url": "https://qwenlm.github.io/blog/qwen2.5/",
        "title": "Qwen2.5 official blog",
        "notes": "Official Qwen model-family release notes for Chinese capability and deployment selection.",
        "terms": "qwen model selection chinese deployment",
    },
    {
        "url": "https://github.com/QwenLM/Qwen3",
        "title": "Qwen3 GitHub repository",
        "notes": "Official Qwen3 repository for open model ecosystem and deployment selection.",
        "terms": "qwen qwen3 model selection open model",
    },
    {
        "url": "https://arxiv.org/abs/2201.11903",
        "title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        "notes": "CoT source paper; frames chain-of-thought as intermediate reasoning steps that improve multi-step tasks.",
        "terms": "cot chain thought reasoning inference hallucination scaling law",
    },
    {
        "url": "https://arxiv.org/abs/2203.11171",
        "title": "Self-Consistency Improves Chain of Thought Reasoning in Language Models",
        "notes": "Self-consistency paper; useful for explaining multi-sample reasoning and majority-style selection.",
        "terms": "cot chain thought reasoning self-consistency sampling",
    },
    {
        "url": "https://arxiv.org/abs/2210.03629",
        "title": "ReAct: Synergizing Reasoning and Acting in Language Models",
        "notes": "ReAct paper; connects reasoning traces with tool/action/observation loops in agent systems.",
        "terms": "react reasoning action observation agent cot tool",
    },
    {
        "url": "https://arxiv.org/abs/2205.11916",
        "title": "Large Language Models are Zero-Shot Reasoners",
        "notes": "Zero-shot CoT paper; explains how simple reasoning triggers can elicit latent multi-step reasoning.",
        "terms": "cot chain thought reasoning zero-shot prompt",
    },
    {
        "url": "https://arxiv.org/abs/2212.10403",
        "title": "Least-to-Most Prompting Enables Complex Reasoning in Large Language Models",
        "notes": "Least-to-most prompting source for decomposing complex reasoning into smaller subproblems.",
        "terms": "cot reasoning least-to-most decomposition prompt",
    },
    {
        "url": "https://arxiv.org/abs/2305.10601",
        "title": "Tree of Thoughts: Deliberate Problem Solving with Large Language Models",
        "notes": "Tree-of-Thought source for contrasting linear CoT with search-style reasoning.",
        "terms": "tree thought tot reasoning search sampling",
    },
    {
        "url": "https://arxiv.org/abs/2001.08361",
        "title": "Scaling Laws for Neural Language Models",
        "notes": "OpenAI scaling laws paper; primary source for parameter/data/compute power-law behavior.",
        "terms": "scaling law parameter data compute loss chinchilla",
    },
    {
        "url": "https://arxiv.org/abs/2203.15556",
        "title": "Training Compute-Optimal Large Language Models",
        "notes": "Chinchilla paper; explains why data/model-size balance matters for compute-optimal training.",
        "terms": "scaling law chinchilla compute optimal data parameter",
    },
    {
        "url": "https://arxiv.org/abs/2109.07958",
        "title": "TruthfulQA: Measuring How Models Mimic Human Falsehoods",
        "notes": "TruthfulQA paper; primary benchmark source for truthfulness and hallucination-adjacent failure modes.",
        "terms": "truthfulqa hallucination truthfulness falsehood",
    },
    {
        "url": "https://arxiv.org/abs/2303.08896",
        "title": "SelfCheckGPT: Zero-Resource Black-Box Hallucination Detection for Generative Large Language Models",
        "notes": "SelfCheckGPT paper; useful for explaining consistency-based hallucination detection.",
        "terms": "hallucination selfcheckgpt detection consistency",
    },
    {
        "url": "https://arxiv.org/abs/2311.05232",
        "title": "A Survey on Hallucination in Large Language Models: Principles, Taxonomy, Challenges, and Open Questions",
        "notes": "Hallucination survey source for taxonomy, causes, and mitigation framing.",
        "terms": "hallucination taxonomy mitigation survey",
    },
    {
        "url": "https://arxiv.org/abs/2307.03172",
        "title": "Lost in the Middle: How Language Models Use Long Contexts",
        "notes": "Long-context paper; supports discussion of context length limits and retrieval/attention failure modes.",
        "terms": "context length attention reasoning hallucination inference",
    },
    {
        "url": "https://arxiv.org/abs/2306.17806",
        "title": "How Language Model Hallucinations Can Snowball",
        "notes": "Hallucination snowballing paper; useful for explaining why early wrong tokens can compound.",
        "terms": "hallucination snowball error propagation reasoning",
    },
    {
        "url": "https://arxiv.org/abs/2402.03620",
        "title": "Chain-of-Thought Reasoning Without Prompting",
        "notes": "Reasoning paper; useful for separating latent reasoning ability from prompt-trigger mechanics.",
        "terms": "cot chain thought reasoning prompt latent",
    },
    {
        "url": "https://arxiv.org/abs/2005.14165",
        "title": "Language Models are Few-Shot Learners",
        "notes": "GPT-3 paper; primary source for few-shot prompting and scale-driven capability discussion.",
        "terms": "scaling law few-shot reasoning prompt parameter",
    },
    {
        "url": "https://arxiv.org/abs/2204.02311",
        "title": "PaLM: Scaling Language Modeling with Pathways",
        "notes": "PaLM paper; useful for connecting model scale with reasoning and multilingual capability changes.",
        "terms": "scaling law reasoning parameter data compute",
    },
    {
        "url": "https://arxiv.org/abs/2206.07682",
        "title": "Emergent Abilities of Large Language Models",
        "notes": "Emergent abilities paper; supports discussion of non-linear capability changes under scale.",
        "terms": "scaling law emergent reasoning capability",
    },
    {
        "url": "https://arxiv.org/abs/2206.04615",
        "title": "Beyond the Imitation Game: Quantifying and extrapolating the capabilities of language models",
        "notes": "BIG-bench paper; benchmark source for reasoning and scaling behavior across tasks.",
        "terms": "scaling law reasoning benchmark big-bench",
    },
    {
        "url": "https://arxiv.org/abs/2203.14465",
        "title": "STaR: Bootstrapping Reasoning With Reasoning",
        "notes": "STaR paper; explains bootstrapping rationales and reasoning traces during training.",
        "terms": "cot reasoning rationale bootstrapping training",
    },
    {
        "url": "https://arxiv.org/abs/2211.10435",
        "title": "Program of Thoughts Prompting: Disentangling Computation from Reasoning for Numerical Reasoning Tasks",
        "notes": "Program-of-Thoughts paper; contrasts natural-language CoT with code-like computation traces.",
        "terms": "cot reasoning program thoughts numerical",
    },
    {
        "url": "https://arxiv.org/abs/2211.12588",
        "title": "PAL: Program-aided Language Models",
        "notes": "PAL paper; useful for explaining when tool/code execution beats pure verbal reasoning.",
        "terms": "cot reasoning program tool execution",
    },
    {
        "url": "https://arxiv.org/abs/2303.11366",
        "title": "Reflexion: Language Agents with Verbal Reinforcement Learning",
        "notes": "Reflexion paper; connects reasoning failure, self-reflection, and iterative correction in agents.",
        "terms": "reasoning hallucination reflection agent correction",
    },
    {
        "url": "https://arxiv.org/abs/2303.17651",
        "title": "Self-Refine: Iterative Refinement with Self-Feedback",
        "notes": "Self-Refine paper; formalizes iterative feedback and refinement loops without extra supervised training.",
        "terms": "self-refine self refine reflection feedback iterative agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2308.09687",
        "title": "Graph of Thoughts: Solving Elaborate Problems with Large Language Models",
        "notes": "GoT paper; generalizes linear/tree reasoning into graph-structured thought dependencies and aggregation.",
        "terms": "graph thoughts got tree thought tot reasoning search agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2305.04091",
        "title": "Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning by Large Language Models",
        "notes": "Plan-and-Solve prompting paper; separates planning before solving to reduce missing-step errors.",
        "terms": "plan solve plan-and-solve planning cot reasoning loop",
    },
    {
        "url": "https://arxiv.org/abs/2302.04761",
        "title": "Toolformer: Language Models Can Teach Themselves to Use Tools",
        "notes": "Toolformer paper; source for tool-use learning and API-call augmentation in language models.",
        "terms": "toolformer tool use tool-use action api agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2205.00445",
        "title": "MRKL Systems: A modular, neuro-symbolic architecture that combines large language models, external knowledge sources and discrete reasoning",
        "notes": "MRKL paper; early modular tool-augmented LLM architecture for routing between neural and symbolic tools.",
        "terms": "mrkl tool use modular action agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2305.18323",
        "title": "ReWOO: Decoupling Reasoning from Observations for Efficient Augmented Language Models",
        "notes": "ReWOO paper; separates planner, worker, and solver to reduce repeated observation-dependent reasoning.",
        "terms": "rewoo reasoning observation planner worker solver tool use agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2308.08155",
        "title": "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation",
        "notes": "AutoGen paper; source for multi-agent conversation loops and orchestrator/worker collaboration patterns.",
        "terms": "autogen multi-agent agent loop orchestrator worker conversation",
    },
    {
        "url": "https://arxiv.org/abs/2305.16291",
        "title": "Voyager: An Open-Ended Embodied Agent with Large Language Models",
        "notes": "Voyager paper; connects skill library, exploration, feedback, and lifelong agent improvement.",
        "terms": "voyager agent loop skill memory reflection embodied agent",
    },
    {
        "url": "https://arxiv.org/abs/2304.03442",
        "title": "Generative Agents: Interactive Simulacra of Human Behavior",
        "notes": "Generative Agents paper; source for memory stream, reflection, and planning in agent behavior.",
        "terms": "generative agents memory reflection planning agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2310.08560",
        "title": "MemGPT: Towards LLMs as Operating Systems",
        "notes": "MemGPT paper; source for memory hierarchy and context management in long-running agents.",
        "terms": "memgpt memory context agent loop working memory long-term memory",
    },
    {
        "url": "https://arxiv.org/abs/2303.17580",
        "title": "HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face",
        "notes": "HuggingGPT paper; source for planner-style tool/model selection and execution orchestration.",
        "terms": "hugginggpt planning execution tool use agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2307.16789",
        "title": "ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs",
        "notes": "ToolLLM paper; source for API/tool-use planning, tool selection, and execution traces.",
        "terms": "toolllm tool use api planning execution agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2305.15334",
        "title": "Gorilla: Large Language Model Connected with Massive APIs",
        "notes": "Gorilla paper; source for API-calling accuracy and tool schema grounding.",
        "terms": "gorilla api tool use tool schema agent loop",
    },
    {
        "url": "https://arxiv.org/abs/2210.03350",
        "title": "Measuring and Narrowing the Compositionality Gap in Language Models",
        "notes": "Compositionality gap paper; useful for explaining why models can produce steps yet miss final answers.",
        "terms": "cot reasoning compositionality hallucination",
    },
    {
        "url": "https://arxiv.org/abs/2211.02011",
        "title": "Inverse Scaling Prize: Second Round Winners",
        "notes": "Inverse scaling source; supports discussion of tasks where larger models can amplify specific failures.",
        "terms": "scaling law inverse scaling hallucination failure",
    },
    {
        "url": "https://arxiv.org/abs/2212.08073",
        "title": "Constitutional AI: Harmlessness from AI Feedback",
        "notes": "Constitutional AI paper; useful for discussing alignment pressure and refusal/truthfulness behavior.",
        "terms": "hallucination alignment truthfulness rlhf",
    },
    {
        "url": "https://arxiv.org/abs/2310.06825",
        "title": "Large Language Models Cannot Self-Correct Reasoning Yet",
        "notes": "Self-correction paper; useful for explaining limits of reflection-style reasoning repair.",
        "terms": "reasoning self-correct hallucination reflection",
    },
    {
        "url": "https://semver.org/",
        "title": "Semantic Versioning 2.0.0",
        "notes": "Canonical SemVer specification for major/minor/patch compatibility and breaking-change signaling.",
        "terms": "skill version semver semantic versioning breaking change sdk plugin manifest",
    },
    {
        "url": "https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases",
        "title": "GitHub Docs: About releases",
        "notes": "GitHub release documentation for versioned distribution, changelogs, source archives, and release artifacts.",
        "terms": "skill version release github semver plugin sdk publish",
    },
    {
        "url": "https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes",
        "title": "GitHub Docs: Automatically generated release notes",
        "notes": "GitHub release-note automation source for version communication and maintainable upgrade records.",
        "terms": "skill version release notes changelog github deprecation migration",
    },
    {
        "url": "https://docs.github.com/en/actions/writing-workflows",
        "title": "GitHub Docs: Writing workflows",
        "notes": "GitHub Actions workflow documentation for validating, packaging, and publishing Skill repositories.",
        "terms": "skill github actions workflow validate publish ci plugin sdk",
    },
    {
        "url": "https://docs.github.com/en/webhooks",
        "title": "GitHub Docs: Webhooks",
        "notes": "GitHub webhook documentation for repository-driven sync, validation, and publication triggers.",
        "terms": "skill webhook github sync publish registry plugin workflow",
    },
    {
        "url": "https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners",
        "title": "GitHub Docs: About CODEOWNERS",
        "notes": "CODEOWNERS documentation for review ownership and governance in shared Skill repositories.",
        "terms": "skill codeowners github review ownership permission publish",
    },
    {
        "url": "https://docs.github.com/en/packages/learn-github-packages/introduction-to-github-packages",
        "title": "GitHub Docs: Introduction to GitHub Packages",
        "notes": "GitHub Packages documentation for package registry concepts, publishing, and dependency distribution.",
        "terms": "skill registry package github publish version dependency plugin sdk",
    },
    {
        "url": "https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps",
        "title": "GitHub Docs: About creating GitHub Apps",
        "notes": "GitHub Apps documentation for permission-scoped automation against repositories and organizations.",
        "terms": "skill github app permission automation webhook registry",
    },
    {
        "url": "https://docs.github.com/en/rest/releases/releases?apiVersion=2022-11-28",
        "title": "GitHub REST API: Releases",
        "notes": "GitHub Releases API documentation for automating release creation, lookup, and asset management.",
        "terms": "skill release api github version publish automation",
    },
    {
        "url": "https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/about-dependabot-version-updates",
        "title": "GitHub Docs: About Dependabot version updates",
        "notes": "Dependabot version-update docs for dependency upgrade automation and compatibility maintenance.",
        "terms": "skill dependency version update github semver sdk plugin",
    },
    {
        "url": "https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions",
        "title": "GitHub Docs: Security hardening for GitHub Actions",
        "notes": "GitHub Actions hardening guide for secure CI/CD, token permissions, and third-party action safety.",
        "terms": "skill permission github actions security publish workflow",
    },
    {
        "url": "https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-rulesets/about-rulesets",
        "title": "GitHub Docs: About rulesets",
        "notes": "Repository rulesets documentation for enforcing branch, tag, and workflow governance.",
        "terms": "skill github ruleset governance publish version permission",
    },
    {
        "url": "https://docs.npmjs.com/about-semantic-versioning",
        "title": "npm Docs: About semantic versioning",
        "notes": "npm SemVer guidance for package version ranges, compatibility expectations, and update strategy.",
        "terms": "skill version semver dependency package registry sdk plugin",
    },
    {
        "url": "https://docs.npmjs.com/cli/v10/configuring-npm/package-json#version",
        "title": "npm Docs: package.json version field",
        "notes": "npm package metadata reference for version field semantics in distributable packages.",
        "terms": "skill manifest package version semver registry sdk plugin",
    },
    {
        "url": "https://packaging.python.org/en/latest/specifications/version-specifiers/",
        "title": "Python Packaging: Version specifiers",
        "notes": "Python packaging version specifier reference for dependency constraints and compatibility ranges.",
        "terms": "skill version dependency semver package sdk plugin",
    },
    {
        "url": "https://packaging.python.org/en/latest/specifications/pyproject-toml/",
        "title": "Python Packaging: pyproject.toml specification",
        "notes": "Python project metadata specification for package build configuration and dependency declarations.",
        "terms": "skill manifest package version dependency sdk plugin",
    },
    {
        "url": "https://code.claude.com/docs/en/skills",
        "title": "Claude Code Docs: Skills",
        "notes": "Claude Code Skills documentation for reusable task workflows, file structure, and discovery.",
        "terms": "skill claude code sdk manifest workflow plugin",
    },
    {
        "url": "https://docs.claude.com/en/docs/claude-code/skills",
        "title": "Claude Docs: Claude Code Skills",
        "notes": "Claude Code Skills reference for packaging repeatable capabilities and making them available to agents.",
        "terms": "skill claude code manifest workflow plugin sdk",
    },
    {
        "url": "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview",
        "title": "Claude Platform Docs: Agent Skills overview",
        "notes": "Claude Platform Agent Skills overview for capability packaging and agent tool orchestration.",
        "terms": "skill agent plugin manifest workflow sdk",
    },
    {
        "url": "https://support.claude.com/en/articles/12512180-using-skills-in-claude",
        "title": "Claude Support: Using Skills in Claude",
        "notes": "Claude support article explaining how users apply Skills and what reusable Skill packages contain.",
        "terms": "skill claude usage package workflow plugin",
    },
    {
        "url": "https://modelcontextprotocol.io/docs/concepts/tools",
        "title": "Model Context Protocol Docs: Tools",
        "notes": "MCP tools concept documentation for tool schemas, descriptions, and tool-call boundaries.",
        "terms": "skill tool schema manifest plugin agent permission mcp",
    },
    {
        "url": "https://modelcontextprotocol.io/docs/concepts/prompts",
        "title": "Model Context Protocol Docs: Prompts",
        "notes": "MCP prompts concept documentation for reusable prompt templates and workflow affordances.",
        "terms": "skill prompt workflow manifest plugin agent mcp",
    },
    {
        "url": "https://modelcontextprotocol.io/docs/concepts/resources",
        "title": "Model Context Protocol Docs: Resources",
        "notes": "MCP resources concept documentation for contextual data exposure and agent-readable metadata.",
        "terms": "skill resource manifest plugin agent mcp context",
    },
    {
        "url": "https://modelcontextprotocol.io/specification/2025-06-18/server/tools",
        "title": "Model Context Protocol Specification: Tools",
        "notes": "MCP tool specification for machine-readable tool contracts and annotations.",
        "terms": "skill tool schema specification manifest plugin mcp",
    },
    {
        "url": "https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle",
        "title": "Model Context Protocol Specification: Lifecycle",
        "notes": "MCP lifecycle specification for initialization, capability negotiation, and protocol versioning.",
        "terms": "skill lifecycle version capability negotiation plugin mcp",
    },
)


def run_deep_research_job(job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    query = str(payload.get("query") or payload.get("title") or "").strip()
    extract_limit = _positive_int(payload.get("extract_limit"), default=54)
    search_per_query = _positive_int(payload.get("search_per_query"), default=12)
    provider_mode = str(payload.get("provider") or "auto").strip().lower()
    queries = _build_query_plan(payload, fallback_query=query)
    query_runs: list[dict[str, Any]] = []
    failure_events: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = _seed_payload_evidence(payload)
    if evidence:
        query_runs.append(
            {
                "provider": "manual_seed",
                "query": "user/API provided research evidence",
                "result_count": len(evidence),
                "status": "ok",
            }
        )

    if provider_mode in {"auto", "hybrid", "tavily"}:
        for current_query in queries:
            tavily_results, tavily_failure = _search_tavily(query=current_query, max_results=search_per_query)
            if tavily_failure:
                failure_events.append({"query": current_query, **tavily_failure})
            query_runs.append(
                {
                    "provider": "tavily_search",
                    "query": current_query,
                    "result_count": len(tavily_results),
                    "status": "ok" if tavily_results else "empty",
                }
            )
            evidence.extend(_normalize_tavily_results(tavily_results, query=current_query))
            if len(_dedupe_evidence(evidence)) >= extract_limit:
                break

    quality_gate = payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {}
    seed_threshold = min(extract_limit, _positive_int(quality_gate.get("min_evidence_count"), default=24))
    if provider_mode in {"auto", "hybrid", "brave"} and len(_dedupe_evidence(evidence)) < seed_threshold:
        for current_query in queries:
            brave_results, brave_failure = _search_brave(query=current_query, max_results=search_per_query)
            if brave_failure:
                failure_events.append({"query": current_query, **brave_failure})
            query_runs.append(
                {
                    "provider": "brave_search",
                    "query": current_query,
                    "result_count": len(brave_results),
                    "status": "ok" if brave_results else "empty",
                }
            )
            evidence.extend(_normalize_brave_results(brave_results, query=current_query))
            if len(_dedupe_evidence(evidence)) >= seed_threshold:
                break

    if provider_mode in {"auto", "hybrid", "duckduckgo", "ddg", "ddg_html"} and len(_dedupe_evidence(evidence)) < seed_threshold:
        for current_query in queries:
            ddg_results, ddg_failure = _search_duckduckgo_lite(query=current_query, max_results=search_per_query)
            if ddg_failure:
                failure_events.append({"query": current_query, **ddg_failure})
            query_runs.append(
                {
                    "provider": "duckduckgo_lite",
                    "query": current_query,
                    "result_count": len(ddg_results),
                    "status": "ok" if ddg_results else "empty",
                }
            )
            evidence.extend(_normalize_duckduckgo_results(ddg_results, query=current_query))
            if len(_dedupe_evidence(evidence)) >= seed_threshold:
                break

    seeded_evidence = []
    if len(_dedupe_evidence(evidence)) < seed_threshold:
        seeded_evidence = _seeded_first_party_evidence(payload, queries=queries, existing=evidence)
    if seeded_evidence:
        evidence.extend(seeded_evidence)
        query_runs.append(
            {
                "provider": "first_party_seed",
                "query": "curated first-party source expansion",
                "result_count": len(seeded_evidence),
                "status": "ok",
            }
        )

    evidence = _dedupe_evidence(evidence)[:extract_limit]
    source_notes = _build_source_notes(evidence)
    status = "ready" if evidence else "failed"
    provider_chain = ["tavily_search"] if provider_mode in {"auto", "hybrid", "tavily"} else []
    if any(item.get("provider") == "manual_seed" for item in query_runs):
        provider_chain.append("manual_seed")
    if any(item.get("provider") == "brave_search" for item in query_runs):
        provider_chain.append("brave_search")
    if any(item.get("provider") == "duckduckgo_lite" for item in query_runs):
        provider_chain.append("duckduckgo_lite")
    if seeded_evidence:
        provider_chain.append("first_party_seed")
    return {
        "status": status,
        "flow": "deep_research",
        "execution_mode": "native_backend",
        "query": query,
        "queries": queries,
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence": evidence,
        "source_notes": source_notes,
        "provider_chain": provider_chain,
        "query_runs": query_runs,
        "provider_diagnostics": {
            "failure_events": failure_events,
            "configured_provider": provider_mode,
            "fallback_policy": "native backend uses explicit research_queries first, then compact fallback queries; provider order is Tavily -> Brave -> DuckDuckGo Lite -> curated first-party seeds.",
        },
        "result_summary": {
            "status": "ok" if evidence else "empty",
            "execution_mode": "native_backend",
            "evidence_count": len(evidence),
            "query_count": len(queries),
            "providers_used": sorted({item["provider"] for item in query_runs if item.get("result_count")}),
            "provider_success_count": len({item["provider"] for item in query_runs if item.get("result_count")}),
            "next_action": "research 已完成；请生成标题、摘要、目录和开头钩子预览。"
            if evidence
            else "research 没有得到可用 evidence；请补充搜索 key 或降低质量门槛后重试。",
        },
        "next_action": "请继续生成标题/摘要/目录/开头钩子预览。" if evidence else "请修复 research evidence 为空的问题后重试。",
    }


def _search_tavily(*, query: str, max_results: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    keys = _split_keys(
        os.getenv("AIMAGICIAN_TAVILY_API_KEYS"),
        os.getenv("AIMAGICIAN_TAVILY_API_KEY"),
        os.getenv("TAVILY_API_KEYS"),
        os.getenv("TAVILY_API_KEY"),
        os.getenv("TAVILY_API_KEY_FALLBACK"),
    )
    if not keys:
        return [], {"provider": "tavily_search", "classification": "missing_config", "detail": "No Tavily API key configured."}
    last_failure: dict[str, Any] | None = None
    for index, api_key in enumerate(keys, start=1):
        try:
            response = requests.post(
                TAVILY_SEARCH_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "query": query[:400],
                    "search_depth": "advanced",
                    "max_results": max(1, min(20, max_results)),
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=45,
            )
            if response.status_code in {401, 403, 429}:
                last_failure = {
                    "provider": "tavily_search",
                    "classification": "quota_or_auth",
                    "detail": f"key_index={index} HTTP {response.status_code}",
                }
                continue
            if response.status_code == 432:
                last_failure = {
                    "provider": "tavily_search",
                    "classification": "quota_or_auth",
                    "detail": f"key_index={index} HTTP 432 usage_limit",
                }
                continue
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results")
            return (results if isinstance(results, list) else []), None
        except Exception as exc:
            last_failure = {"provider": "tavily_search", "classification": "network", "detail": str(exc)[:400]}
            continue
    return [], last_failure


def _search_brave(*, query: str, max_results: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    keys = _split_keys(
        os.getenv("AIMAGICIAN_BRAVE_SEARCH_API_KEYS"),
        os.getenv("AIMAGICIAN_BRAVE_SEARCH_API_KEY"),
        os.getenv("BRAVE_SEARCH_API_KEYS"),
        os.getenv("BRAVE_SEARCH_API_KEY"),
        os.getenv("BRAVE_API_KEYS"),
        os.getenv("BRAVE_API_KEY"),
    )
    if not keys:
        return [], {"provider": "brave_search", "classification": "missing_config", "detail": "No Brave Search API key configured."}
    last_failure: dict[str, Any] | None = None
    for index, api_key in enumerate(keys, start=1):
        try:
            response = requests.get(
                BRAVE_WEB_SEARCH_ENDPOINT,
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={
                    "q": _compact_query(query, limit=400),
                    "count": max(1, min(20, max_results)),
                    "search_lang": "zh",
                    "ui_lang": "zh-CN",
                    "country": "CN",
                    "safesearch": "moderate",
                    "text_decorations": "false",
                    "result_filter": "web",
                },
                timeout=45,
            )
            if response.status_code in {401, 403, 429}:
                last_failure = {
                    "provider": "brave_search",
                    "classification": "quota_or_auth",
                    "detail": f"key_index={index} HTTP {response.status_code}",
                }
                continue
            response.raise_for_status()
            payload = response.json()
            web = payload.get("web") if isinstance(payload, dict) else {}
            results = web.get("results") if isinstance(web, dict) else []
            return (results if isinstance(results, list) else []), None
        except Exception as exc:
            last_failure = {"provider": "brave_search", "classification": "network", "detail": str(exc)[:400]}
            continue
    return [], last_failure


def _search_duckduckgo_lite(*, query: str, max_results: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        response = requests.post(
            DUCKDUCKGO_LITE_ENDPOINT,
            data={"q": _compact_query(query, limit=400)},
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AImagicianResearch/1.0)",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=45,
        )
        response.raise_for_status()
        results = _parse_duckduckgo_lite_results(response.text, limit=max_results)
        return results, None if results else {
            "provider": "duckduckgo_lite",
            "classification": "empty",
            "detail": "DuckDuckGo Lite returned no parseable results.",
        }
    except Exception as exc:
        return [], {"provider": "duckduckgo_lite", "classification": "network", "detail": str(exc)[:400]}


def _build_query_plan(payload: dict[str, Any], *, fallback_query: str) -> list[str]:
    series_entry = payload.get("series_entry") if isinstance(payload.get("series_entry"), dict) else {}
    quality_gate = payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {}
    explicit_queries = _text_list(payload.get("research_queries")) + _text_list(series_entry.get("research_queries"))
    keywords = _text_list(series_entry.get("keywords"))
    title = str(
        payload.get("title")
        or series_entry.get("final_title")
        or series_entry.get("merge_main_title")
        or series_entry.get("draft_title")
        or ""
    ).strip()
    topic = str(series_entry.get("topic_summary") or "").strip()

    candidates: list[str] = []
    candidates.extend(explicit_queries)
    if fallback_query:
        candidates.extend(part for part in re.split(r"\s+\|\s+", fallback_query) if part.strip())
        candidates.append(fallback_query)
    if title and keywords:
        candidates.append(" ".join([title, *keywords[:6]]))
    if topic and keywords:
        candidates.append(" ".join([topic, *keywords[:6]]))
    if keywords:
        candidates.append(" ".join(keywords[:10]))
    candidates.extend(_derived_hotspot_queries(fallback_query))

    base_terms = explicit_queries[0] if explicit_queries else " ".join([title, *keywords[:6]]).strip()
    for domain in _text_list(quality_gate.get("first_party_domains"))[:5]:
        if base_terms:
            candidates.append(f"{base_terms} site:{domain}")

    planned: list[str] = []
    for candidate in candidates:
        query = _compact_query(candidate)
        if query and query not in planned:
            planned.append(query)
        if len(planned) >= 10:
            break
    return planned


def _seed_payload_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("seed_evidence")
    if raw_items is None:
        raw_items = payload.get("manual_evidence")
    if raw_items is None:
        raw_items = payload.get("evidence")
    if not isinstance(raw_items, list):
        return []
    seeded: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url") or item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("source_title") or item.get("title") or url).strip()
        notes = str(item.get("source_notes") or item.get("summary") or item.get("content") or "").strip()
        seeded.append(
            {
                "id": f"manual-seed-{index}",
                "provider": str(item.get("provider") or "manual_seed").strip() or "manual_seed",
                "query": str(item.get("query") or "user/API provided research evidence").strip(),
                "source_title": title,
                "source_url": url,
                "source_domain": urlparse(url).netloc or urlparse(url).scheme,
                "source_notes": notes,
                "summary": notes,
                "score": item.get("score") or 0.9,
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return seeded


def _derived_hotspot_queries(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    lowered = normalized.lower()
    queries: list[str] = []
    ascii_terms = re.findall(r"[A-Za-z][A-Za-z0-9._+-]*(?:\s+[A-Za-z][A-Za-z0-9._+-]*){0,5}", normalized)
    compact_ascii = " ".join(term.strip() for term in ascii_terms if term.strip())
    if compact_ascii:
        queries.append(compact_ascii)
    if "coding agent" in lowered or "ai 编程" in lowered or "编程工作流" in normalized:
        queries.extend(
            [
                "AI coding agent workflow 2026 Claude Code OpenAI Codex Cursor Devin",
                "AI software engineering agents workflow human review pull request 2026",
                "AI coding agents benchmark Claude Code Codex Devin Cursor 2026",
            ]
        )
    return queries


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[\n,，、|]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _compact_query(query: str, *, limit: int = 320) -> str:
    normalized = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    parts = re.split(r"[\s,，、|]+", normalized)
    kept: list[str] = []
    for part in parts:
        candidate = " ".join([*kept, part]).strip()
        if len(candidate) > limit:
            break
        kept.append(part)
    compacted = " ".join(kept).strip()
    return compacted or normalized[:limit].strip()


def _seeded_first_party_evidence(
    payload: dict[str, Any],
    *,
    queries: list[str],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    quality_gate = payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {}
    allowed_domains = {str(item).strip().lower() for item in quality_gate.get("first_party_domains") or [] if str(item).strip()}
    if not allowed_domains:
        return []
    existing_urls = {str(item.get("source_url") or "").strip() for item in existing if isinstance(item, dict)}
    series_entry = payload.get("series_entry") if isinstance(payload.get("series_entry"), dict) else {}
    topic_text = " ".join(
        [
            str(payload.get("query") or ""),
            str(payload.get("title") or ""),
            str(series_entry.get("topic_summary") or ""),
            " ".join(_text_list(series_entry.get("keywords"))),
            " ".join(queries),
        ]
    ).lower()
    scored_evidence: list[tuple[int, int, dict[str, Any]]] = []
    for index, seed in enumerate(FIRST_PARTY_SOURCE_SEEDS, start=1):
        url = seed["url"]
        if url in existing_urls:
            continue
        if not any(domain in url.lower() for domain in allowed_domains):
            continue
        seed_terms = {term for term in re.split(r"[\s,，、|/]+", seed.get("terms", "")) if term}
        match_score = sum(1 for term in seed_terms if term.lower() in topic_text)
        if seed_terms and match_score <= 0:
            continue
        scored_evidence.append(
            (
                max(1, match_score),
                index,
                {
                    "id": f"first-party-seed-{index}",
                    "provider": "first_party_seed",
                    "query": "curated first-party source expansion",
                    "source_title": seed["title"],
                    "source_url": url,
                    "source_domain": urlparse(url).netloc,
                    "source_notes": seed["notes"],
                    "summary": seed["notes"],
                    "score": min(0.95, 0.7 + match_score * 0.03),
                    "retrieved_at": datetime.now(UTC).isoformat(),
                },
            )
        )
    scored_evidence.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in scored_evidence]


def _normalize_tavily_results(results: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or url).strip()
        content = str(item.get("content") or item.get("snippet") or "").strip()
        normalized.append(
            {
                "id": f"tavily-{index}",
                "provider": "tavily_search",
                "query": query,
                "source_title": title,
                "source_url": url,
                "source_domain": urlparse(url).netloc,
                "source_notes": content,
                "summary": content,
                "score": item.get("score"),
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return normalized


def _normalize_brave_results(results: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or url).strip()
        snippets = [str(item.get("description") or "").strip()]
        extra = item.get("extra_snippets") if isinstance(item.get("extra_snippets"), list) else []
        snippets.extend(str(part).strip() for part in extra[:2] if str(part).strip())
        content = " ".join(part for part in snippets if part).strip()
        normalized.append(
            {
                "id": f"brave-{index}",
                "provider": "brave_search",
                "query": query,
                "source_title": title,
                "source_url": url,
                "source_domain": urlparse(url).netloc,
                "source_notes": content,
                "summary": content,
                "score": max(0.1, 1.0 - index / 25),
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return normalized


def _normalize_duckduckgo_results(results: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or url).strip()
        snippet = str(item.get("snippet") or "").strip()
        normalized.append(
            {
                "id": f"duckduckgo-{index}",
                "provider": "duckduckgo_lite",
                "query": query,
                "source_title": title,
                "source_url": url,
                "source_domain": urlparse(url).netloc,
                "source_notes": snippet,
                "summary": snippet,
                "score": max(0.1, 1.0 - index / 25),
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    return normalized


def _parse_duckduckgo_lite_results(html_text: str, *, limit: int) -> list[dict[str, str]]:
    rows = re.finditer(
        r"<a(?P<attrs>[^>]*class=['\"][^'\"]*result-link[^'\"]*['\"][^>]*)>(?P<title>.*?)</a>"
        r"(?P<tail>.*?)(?=<a[^>]+class=['\"][^'\"]*result-link|</table>|$)",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, str]] = []
    for match in rows:
        attrs = match.group("attrs")
        href_match = re.search(r"href=['\"](?P<href>[^'\"]+)['\"]", attrs, flags=re.IGNORECASE)
        if not href_match:
            continue
        href = href_match.group("href")
        title_html = match.group("title")
        tail = match.group("tail")
        url = _decode_duckduckgo_url(unescape(href))
        if not url.startswith(("http://", "https://")):
            continue
        title = _strip_html(title_html)
        snippet_match = re.search(
            r"<td[^>]+class=['\"]result-snippet['\"][^>]*>(?P<snippet>.*?)</td>",
            tail,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippet = _strip_html(snippet_match.group("snippet")) if snippet_match else ""
        results.append({"title": title or url, "url": url, "snippet": snippet})
        if len(results) >= max(1, min(20, limit)):
            break
    return results


def _decode_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in evidence:
        url = str(item.get("source_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def _build_source_notes(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    lines = ["# Research Evidence", ""]
    for index, item in enumerate(evidence, start=1):
        title = str(item.get("source_title") or item.get("source_url") or f"Source {index}").strip()
        url = str(item.get("source_url") or "").strip()
        notes = str(item.get("source_notes") or item.get("summary") or "").strip()
        lines.append(f"## {index}. {title}")
        if url:
            lines.append(f"- URL: {url}")
        if notes:
            lines.append(f"- Notes: {notes[:1200]}")
        lines.append("")
    return "\n".join(lines).strip()


def _split_keys(*values: str | None) -> list[str]:
    keys: list[str] = []
    for value in values:
        for part in str(value or "").replace(";", ",").split(","):
            key = part.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
