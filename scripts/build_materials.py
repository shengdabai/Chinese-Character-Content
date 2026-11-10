from __future__ import annotations

import csv
import gzip
import html
import json
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pypinyin import Style, lazy_pinyin
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
CONTENT = ROOT / "content"
PDF = ROOT / "pdf"
SITE = ROOT / "docs"

CC_CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
CEDICT_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
CEDICT_MAX_TEXT_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class Term:
    text: str
    meaning: str


@dataclass(frozen=True)
class ProductPack:
    slug: str
    title: str
    audience: str
    promise: str
    deliverables: tuple[str, ...]
    sample_topics: tuple[str, ...]
    why_it_sells: str


PRODUCT_PACKS = [
    ProductPack(
        slug="speak-in-7-days",
        title="Speak in 7 Days: Survival Mandarin",
        audience="Busy zero beginners who need useful spoken Chinese fast.",
        promise="A compact first-week path from greetings to ordering, directions, and basic self-introduction.",
        deliverables=("7 short lessons", "one-page phrase sheets", "daily speaking task", "top 100 character companion"),
        sample_topics=("names", "numbers", "food", "transport", "countries", "time", "help requests"),
        why_it_sells="It gives beginners a clear win in one week instead of starting with abstract character memorization.",
    ),
    ProductPack(
        slug="business-trip-kit",
        title="Business Trip Mandarin Kit",
        audience="Professionals traveling to China or working with Chinese-speaking partners.",
        promise="Meeting, taxi, hotel, restaurant, invoice, and follow-up language in one printable kit.",
        deliverables=("business phrasebook", "meeting scripts", "role-play cards", "invoice/payment vocabulary"),
        sample_topics=("introductions", "meetings", "schedules", "prices", "payments", "follow-up messages"),
        why_it_sells="It maps directly to workplace situations where learners feel immediate pressure to speak.",
    ),
    ProductPack(
        slug="hsk-speaking-bridge",
        title="HSK 1-3 Speaking Bridge",
        audience="Learners preparing for HSK 1-3 who also want practical spoken fluency.",
        promise="Turn high-frequency characters and exam vocabulary into short spoken responses.",
        deliverables=("HSK-inspired lesson sequence", "sentence substitution drills", "oral answer prompts", "top 600 list"),
        sample_topics=("family", "daily routine", "opinions", "plans", "travel", "shopping"),
        why_it_sells="Many HSK materials are reading-heavy; this positions the same foundation as a speaking product.",
    ),
    ProductPack(
        slug="3500-character-finder",
        title="3500 Character Finder for Foreign Learners",
        audience="Self-learners, teachers, translators, and curriculum designers.",
        promise="A fast English/pinyin reference for the 3500 common characters, sorted for lookup and teaching.",
        deliverables=("3500-character PDF", "CSV reference", "web reference", "category labels", "frequency ranks"),
        sample_topics=("pinyin lookup", "frequency lookup", "function words", "people", "business", "time"),
        why_it_sells="It converts a raw Chinese list into a usable foreign-learner reference product.",
    ),
]


FOUR_WEEK_PLAN = [
    {
        "week": "Week 1",
        "theme": "Survival Speaking",
        "goals": "Greet people, introduce yourself, say numbers, and ask simple questions.",
        "daily_routine": "10 minutes character reading, 10 minutes phrase shadowing, 5 minutes self-introduction.",
        "deliverable": "Record a 30-second self-introduction.",
    },
    {
        "week": "Week 2",
        "theme": "Daily Life and Travel",
        "goals": "Order food, ask for directions, use time words, and handle short travel exchanges.",
        "daily_routine": "Review 20 characters, read 10 phrases aloud, complete one role-play.",
        "deliverable": "Complete a restaurant or taxi role-play without English notes.",
    },
    {
        "week": "Week 3",
        "theme": "HSK 1-2 Speaking Bridge",
        "goals": "Turn core words into short answers about family, work, schedule, and preferences.",
        "daily_routine": "Read a Top 300 character set, build 5 sentences, answer 3 oral prompts.",
        "deliverable": "Answer 10 HSK-style personal questions aloud.",
    },
    {
        "week": "Week 4",
        "theme": "Business Starter",
        "goals": "Introduce your company, confirm meetings, discuss price and follow-up.",
        "daily_routine": "Practice one business script, substitute your real company details, record and revise.",
        "deliverable": "Deliver a 60-second business introduction and meeting follow-up.",
    },
]


SPEAKING_DRILLS = [
    ("Introduce yourself", "你好，我叫 __。我是 __。", "Hello, my name is __. I am __.", "Replace name, country, job."),
    ("Ask someone's name", "你叫什么名字？", "What is your name?", "Ask, listen, and answer."),
    ("Say your country", "我是 __ 人。", "I am from __.", "Use 美国/英国/西班牙/中国."),
    ("Say what you speak", "我会说一点中文。", "I can speak a little Chinese.", "Change 中文 to 英文."),
    ("Ask for time", "现在几点？", "What time is it now?", "Answer with __ 点."),
    ("Order tea", "我要一杯茶。", "I would like a cup of tea.", "Change tea to water or coffee."),
    ("Ask for directions", "请问，地铁站怎么走？", "Excuse me, how do I get to the subway station?", "Change destination."),
    ("Confirm a meeting", "请确认会议时间。", "Please confirm the meeting time.", "Add tomorrow or afternoon."),
    ("Reply later", "我稍后回复你。", "I will reply to you later.", "Use in a business chat."),
    ("Ask for price", "这个多少钱？", "How much is this?", "Change this to product/service."),
    ("Ask for discount", "可以有折扣吗？", "Can there be a discount?", "Practice polite tone."),
    ("Give an opinion", "我觉得这个很好。", "I think this is very good.", "Change adjective."),
    ("Give a reason", "因为今天很忙，所以我不能去。", "Because I am busy today, I cannot go.", "Change reason."),
    ("Change a plan", "我们需要改变计划。", "We need to change the plan.", "Add time or reason."),
    ("Introduce role", "我负责中国市场。", "I am responsible for the China market.", "Change market/department."),
]


BUSINESS_PHRASES = [
    ("Self-introduction", "我是销售经理。", "I am a sales manager.", "wǒ shì xiāo shòu jīng lǐ"),
    ("Company", "我在一家美国公司工作。", "I work at an American company.", "wǒ zài yì jiā měi guó gōng sī gōng zuò"),
    ("Responsibility", "我负责中国市场。", "I am responsible for the China market.", "wǒ fù zé zhōng guó shì chǎng"),
    ("Meeting time", "我们明天上午十点开会。", "We will meet tomorrow at 10 a.m.", "wǒ men míng tiān shàng wǔ shí diǎn kāi huì"),
    ("Confirmation", "请确认会议时间。", "Please confirm the meeting time.", "qǐng què rèn huì yì shí jiān"),
    ("Materials", "我把资料发给你。", "I will send you the materials.", "wǒ bǎ zī liào fā gěi nǐ"),
    ("Follow-up", "我稍后回复你。", "I will reply to you later.", "wǒ shāo hòu huí fù nǐ"),
    ("Invoice", "请把发票发给我。", "Please send me the invoice.", "qǐng bǎ fā piào fā gěi wǒ"),
    ("Payment", "什么时候付款？", "When is the payment?", "shén me shí hou fù kuǎn"),
    ("Price", "这个价格合适吗？", "Is this price suitable?", "zhè ge jià gé hé shì ma"),
    ("Discount", "可以有折扣吗？", "Can there be a discount?", "kě yǐ yǒu zhé kòu ma"),
    ("Contract", "我们需要看合同。", "We need to review the contract.", "wǒ men xū yào kàn hé tóng"),
]


PLACEMENT_CHECKLIST = [
    ("Beginner", "Can greet someone and say your name.", "Say: 你好，我叫 __。"),
    ("Beginner", "Can read numbers 1-10.", "Read a phone number aloud."),
    ("Beginner", "Can say your country and language.", "我是 __ 人。我会说 __。"),
    ("HSK1", "Can answer basic personal questions.", "Answer: 你叫什么名字？你是哪国人？"),
    ("HSK1", "Can use time words.", "Say what you will do tomorrow morning."),
    ("HSK2", "Can order food and drink.", "Order one drink and one food item."),
    ("HSK2", "Can ask for directions.", "Ask how to get to a hotel or subway station."),
    ("HSK3", "Can give a short opinion.", "Use 我觉得...因为..."),
    ("HSK3", "Can explain a plan.", "Say one plan for next month."),
    ("Business Starter", "Can introduce company and role.", "Say company, title, and responsibility."),
    ("Business Starter", "Can confirm a meeting.", "Confirm time and follow-up."),
    ("Business Starter", "Can ask about price/payment.", "Ask about price, discount, invoice, or payment."),
]


LOOKUP_CATEGORIES = {
    "People & Pronouns": set("我你他她它人们子女父母爸妈先老友同"),
    "Numbers & Measures": set("一二三四五六七八九十百千万亿个只本些第半两"),
    "Time": set("年月日天时分秒早晚昨今明现前后已再"),
    "Places & Movement": set("上下左右东西南北中里外去来到回出入走路站场店家国"),
    "Business & Work": set("工公司会商市卖买钱价合客户产销发票付部经理"),
    "Question & Function": set("吗呢吧的了是不有在和也都就又很更最把被给让从向为"),
    "Actions": set("说看听读写学做吃喝开关用要想知能会见找问"),
}


EXAMPLE_WORD_OVERRIDES = {
    "我": ("我们", "我的", "自我"),
    "你": ("你好", "你们", "你的"),
    "他": ("他们", "他的", "他人"),
    "她": ("她们", "她的"),
    "是": ("不是", "可是", "总是"),
    "有": ("没有", "有用", "有名"),
    "不": ("不是", "不好", "不用"),
    "会": ("会议", "开会", "会说"),
    "说": ("说话", "说明", "小说"),
    "学": ("学生", "学校", "学习"),
    "中": ("中国", "中文", "中间"),
    "国": ("中国", "美国", "国家"),
    "人": ("人们", "中国人", "个人"),
    "名": ("名字", "有名", "名单"),
    "字": ("名字", "汉字", "文字"),
    "电": ("电话", "电脑", "电梯"),
    "话": ("电话", "说话", "对话"),
    "工": ("工作", "工人", "工资"),
    "作": ("工作", "作业", "合作"),
    "公": ("公司", "办公室", "公共"),
    "司": ("公司", "司机", "司法"),
    "商": ("商务", "商店", "商量"),
    "钱": ("付钱", "价钱", "赚钱"),
    "价": ("价格", "价钱", "评价"),
    "安": ("安全", "安排", "平安"),
    "爱": ("爱好", "可爱", "热爱"),
    "吃": ("吃饭", "好吃", "吃完"),
    "喝": ("喝水", "喝茶", "吃喝"),
    "走": ("走路", "走开", "走进"),
    "来": ("回来", "进来", "来到"),
    "去": ("出去", "回去", "去年"),
    "时": ("时间", "小时", "同时"),
    "间": ("时间", "房间", "中间"),
    "天": ("今天", "明天", "天气"),
    "月": ("这个月", "下个月", "月亮"),
    "年": ("今年", "去年", "年轻"),
}


LESSONS = [
    {
        "level": "Zero Beginner",
        "title": "Greetings and Names",
        "goal": "Greet people and introduce your name.",
        "terms": [
            Term("你好", "hello"),
            Term("我", "I; me"),
            Term("你", "you"),
            Term("叫", "to be called"),
            Term("什么", "what"),
            Term("名字", "name"),
            Term("是", "to be"),
            Term("老师", "teacher"),
            Term("学生", "student"),
            Term("谢谢", "thank you"),
        ],
        "sentences": [
            ("你好，我叫 David。", "Hello, my name is David."),
            ("你叫什么名字？", "What is your name?"),
            ("我是学生。", "I am a student."),
        ],
        "speaking_task": "Introduce yourself with: 你好，我叫 __。我是 __。",
    },
    {
        "level": "Zero Beginner",
        "title": "Numbers and Phone Numbers",
        "goal": "Say numbers and read a phone number aloud.",
        "terms": [
            Term("一", "one"),
            Term("二", "two"),
            Term("三", "three"),
            Term("四", "four"),
            Term("五", "five"),
            Term("六", "six"),
            Term("七", "seven"),
            Term("八", "eight"),
            Term("九", "nine"),
            Term("十", "ten"),
            Term("电话", "phone"),
            Term("号码", "number"),
        ],
        "sentences": [
            ("我的电话号码是 13800138000。", "My phone number is 13800138000."),
            ("请再说一遍。", "Please say it one more time."),
        ],
        "speaking_task": "Read your phone number slowly in Chinese.",
    },
    {
        "level": "Zero Beginner",
        "title": "Countries and Languages",
        "goal": "Say where you are from and what languages you speak.",
        "terms": [
            Term("中国", "China"),
            Term("美国", "United States"),
            Term("英国", "United Kingdom"),
            Term("西班牙", "Spain"),
            Term("人", "person"),
            Term("中文", "Chinese language"),
            Term("英文", "English language"),
            Term("说", "to speak"),
            Term("会", "can; know how to"),
        ],
        "sentences": [
            ("我是美国人。", "I am American."),
            ("我会说一点中文。", "I can speak a little Chinese."),
            ("你会说英文吗？", "Can you speak English?"),
        ],
        "speaking_task": "Say your country and one language you speak.",
    },
    {
        "level": "HSK1 Core",
        "title": "Family and People",
        "goal": "Talk about family members.",
        "terms": [
            Term("家", "home; family"),
            Term("爸爸", "father"),
            Term("妈妈", "mother"),
            Term("儿子", "son"),
            Term("女儿", "daughter"),
            Term("朋友", "friend"),
            Term("同学", "classmate"),
            Term("医生", "doctor"),
            Term("工作", "work; job"),
            Term("忙", "busy"),
        ],
        "sentences": [
            ("我家有三个人。", "There are three people in my family."),
            ("我妈妈是医生。", "My mother is a doctor."),
            ("你今天忙吗？", "Are you busy today?"),
        ],
        "speaking_task": "Describe two people in your family.",
    },
    {
        "level": "HSK1 Core",
        "title": "Time and Daily Schedule",
        "goal": "Say basic time and daily actions.",
        "terms": [
            Term("今天", "today"),
            Term("明天", "tomorrow"),
            Term("昨天", "yesterday"),
            Term("现在", "now"),
            Term("上午", "morning"),
            Term("下午", "afternoon"),
            Term("晚上", "evening"),
            Term("点", "o'clock"),
            Term("去", "to go"),
            Term("回", "to return"),
            Term("睡觉", "to sleep"),
        ],
        "sentences": [
            ("现在几点？", "What time is it now?"),
            ("我明天上午去学校。", "I will go to school tomorrow morning."),
            ("我晚上十一点睡觉。", "I sleep at 11 p.m."),
        ],
        "speaking_task": "Say three things you do today.",
    },
    {
        "level": "HSK2 Expansion",
        "title": "Eating and Ordering",
        "goal": "Order simple food and drinks.",
        "terms": [
            Term("吃", "to eat"),
            Term("喝", "to drink"),
            Term("水", "water"),
            Term("茶", "tea"),
            Term("咖啡", "coffee"),
            Term("米饭", "rice"),
            Term("面条", "noodles"),
            Term("菜单", "menu"),
            Term("服务员", "server"),
            Term("买单", "to pay the bill"),
            Term("好吃", "tasty"),
        ],
        "sentences": [
            ("我要一杯茶。", "I would like a cup of tea."),
            ("这个菜很好吃。", "This dish is tasty."),
            ("服务员，买单。", "Server, the bill please."),
        ],
        "speaking_task": "Order one drink and one food item.",
    },
    {
        "level": "HSK2 Expansion",
        "title": "Travel and Directions",
        "goal": "Ask where a place is and how to get there.",
        "terms": [
            Term("机场", "airport"),
            Term("酒店", "hotel"),
            Term("出租车", "taxi"),
            Term("地铁", "subway"),
            Term("车站", "station"),
            Term("地址", "address"),
            Term("左边", "left side"),
            Term("右边", "right side"),
            Term("前面", "front"),
            Term("后面", "back"),
            Term("怎么走", "how to get there"),
        ],
        "sentences": [
            ("酒店在哪里？", "Where is the hotel?"),
            ("请问，地铁站怎么走？", "Excuse me, how do I get to the subway station?"),
            ("机场在前面。", "The airport is ahead."),
        ],
        "speaking_task": "Ask for directions to a hotel or subway station.",
    },
    {
        "level": "HSK3 Expansion",
        "title": "Opinions and Reasons",
        "goal": "Give a simple opinion and reason.",
        "terms": [
            Term("觉得", "to think; to feel"),
            Term("因为", "because"),
            Term("所以", "so"),
            Term("但是", "but"),
            Term("可能", "maybe; possible"),
            Term("重要", "important"),
            Term("问题", "problem; question"),
            Term("办法", "method; solution"),
            Term("容易", "easy"),
            Term("难", "difficult"),
        ],
        "sentences": [
            ("我觉得中文很有意思。", "I think Chinese is interesting."),
            ("因为今天很忙，所以我不能去。", "Because I am busy today, I cannot go."),
            ("这个问题不难。", "This problem is not difficult."),
        ],
        "speaking_task": "Say one opinion and explain why.",
    },
    {
        "level": "HSK3 Expansion",
        "title": "Plans and Changes",
        "goal": "Talk about plans, changes, and completion.",
        "terms": [
            Term("计划", "plan"),
            Term("准备", "to prepare; plan to"),
            Term("已经", "already"),
            Term("还", "still; yet"),
            Term("完成", "to complete"),
            Term("改变", "to change"),
            Term("开始", "to start"),
            Term("结束", "to end"),
            Term("以前", "before"),
            Term("以后", "after; later"),
        ],
        "sentences": [
            ("我准备下个月去中国。", "I plan to go to China next month."),
            ("会议已经开始了。", "The meeting has already started."),
            ("我们需要改变计划。", "We need to change the plan."),
        ],
        "speaking_task": "Describe one plan for next month.",
    },
    {
        "level": "Business Starter",
        "title": "Introducing Your Company",
        "goal": "Introduce your company, role, and department.",
        "terms": [
            Term("公司", "company"),
            Term("部门", "department"),
            Term("职位", "position"),
            Term("经理", "manager"),
            Term("客户", "client"),
            Term("产品", "product"),
            Term("市场", "market"),
            Term("销售", "sales"),
            Term("负责", "to be responsible for"),
            Term("合作", "cooperation"),
        ],
        "sentences": [
            ("我在一家美国公司工作。", "I work at an American company."),
            ("我是销售经理。", "I am a sales manager."),
            ("我负责中国市场。", "I am responsible for the China market."),
        ],
        "speaking_task": "Introduce your company and your role in three sentences.",
    },
    {
        "level": "Business Starter",
        "title": "Meetings and Follow-up",
        "goal": "Handle basic meeting language.",
        "terms": [
            Term("会议", "meeting"),
            Term("开会", "to have a meeting"),
            Term("时间", "time"),
            Term("地点", "place"),
            Term("议程", "agenda"),
            Term("确认", "to confirm"),
            Term("安排", "to arrange"),
            Term("资料", "materials"),
            Term("稍后", "later"),
            Term("回复", "to reply"),
        ],
        "sentences": [
            ("我们明天上午十点开会。", "We will have a meeting tomorrow at 10 a.m."),
            ("请确认会议时间。", "Please confirm the meeting time."),
            ("我稍后回复你。", "I will reply to you later."),
        ],
        "speaking_task": "Confirm a meeting time and say you will reply later.",
    },
    {
        "level": "Business Starter",
        "title": "Prices and Payment",
        "goal": "Ask about price, discount, and payment.",
        "terms": [
            Term("价格", "price"),
            Term("多少钱", "how much money"),
            Term("折扣", "discount"),
            Term("合同", "contract"),
            Term("付款", "payment"),
            Term("发票", "invoice"),
            Term("预算", "budget"),
            Term("成本", "cost"),
            Term("可以", "can; may"),
            Term("合适", "suitable"),
        ],
        "sentences": [
            ("这个价格合适吗？", "Is this price suitable?"),
            ("可以有折扣吗？", "Can there be a discount?"),
            ("请把发票发给我。", "Please send me the invoice."),
        ],
        "speaking_task": "Ask for the price and one possible discount.",
    },
]


def ensure_dirs() -> None:
    for path in [PROCESSED, CONTENT, PDF, SITE, SITE / "assets"]:
        path.mkdir(parents=True, exist_ok=True)


def only_cjk(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    chars = re.findall(r"[\u4e00-\u9fff]", value)
    if len(chars) == 1:
        return chars[0]
    return None


def read_source_data() -> pd.DataFrame:
    df_3500 = pd.read_excel(RAW / "3500常用汉字.xls")
    df_3500["character"] = df_3500["hz"].map(only_cjk)
    df_3500 = df_3500.dropna(subset=["character"]).reset_index(drop=True)
    df_3500["rank_3500"] = df_3500.index + 1

    df_7000 = pd.read_excel(
        RAW / "7000通用汉字.xls",
        engine="xlrd",
        engine_kwargs={"encoding_override": "cp936"},
    )
    df_7000["character"] = df_7000["hz"].map(only_cjk)
    df_7000 = df_7000.dropna(subset=["character"]).reset_index(drop=True)
    df_7000["rank_7000"] = df_7000["xh"]

    df_corpus = pd.read_excel(
        RAW / "Chinese character list from 2.5 billion words corpus ordered by frequency.xlsx"
    )
    df_corpus = df_corpus.rename(
        columns={
            "\xa0serial number": "frequency_rank",
            "character": "character",
            "token": "token",
            "ferquency(per million)": "frequency_per_million",
            "total coverage rate(%)": "coverage_rate_pct",
        }
    )
    df_corpus["character"] = df_corpus["character"].map(only_cjk)
    df_corpus = df_corpus.dropna(subset=["character"])

    merged = pd.DataFrame({"character": sorted(set(df_3500["character"]) | set(df_7000["character"]) | set(df_corpus["character"]))})
    merged = merged.merge(df_3500[["character", "rank_3500"]], on="character", how="left")
    merged = merged.merge(df_7000[["character", "rank_7000"]], on="character", how="left")
    merged = merged.merge(
        df_corpus[
            [
                "character",
                "frequency_rank",
                "token",
                "frequency_per_million",
                "coverage_rate_pct",
            ]
        ],
        on="character",
        how="left",
    )
    merged["in_3500"] = merged["rank_3500"].notna()
    merged["in_7000"] = merged["rank_7000"].notna()
    merged["in_corpus"] = merged["frequency_rank"].notna()
    merged = merged.sort_values(
        by=["frequency_rank", "rank_3500", "rank_7000", "character"],
        na_position="last",
    ).reset_index(drop=True)
    return merged


def download_cedict() -> Path | None:
    gz_path = RAW / "cedict_1_0_ts_utf-8_mdbg.txt.gz"
    txt_path = RAW / "cedict_ts.u8"
    if txt_path.exists():
        return txt_path

    def copy_limited(source, target, limit: int) -> None:
        total = 0
        while chunk := source.read(min(1024 * 1024, limit - total + 1)):
            total += len(chunk)
            if total > limit:
                raise ValueError("CC-CEDICT size limit exceeded")
            target.write(chunk)

    try:
        print("Downloading CC-CEDICT definitions...")
        # Publish the cache only after the complete gzip stream passes its CRC check.
        with tempfile.TemporaryDirectory(prefix=".cedict-", dir=RAW) as directory:
            pending_gz = Path(directory) / gz_path.name
            pending_txt = Path(directory) / txt_path.name
            with urllib.request.urlopen(CC_CEDICT_URL, timeout=30) as response, pending_gz.open("wb") as dst:
                copy_limited(response, dst, CEDICT_MAX_DOWNLOAD_BYTES)
            with gzip.open(pending_gz, "rb") as src, pending_txt.open("wb") as dst:
                copy_limited(src, dst, CEDICT_MAX_TEXT_BYTES)
            pending_gz.replace(gz_path)
            pending_txt.replace(txt_path)
        return txt_path
    except (OSError, EOFError, ValueError) as exc:
        print(f"CC-CEDICT download skipped: {exc}")
        return None


def load_cedict() -> tuple[dict[str, str], dict[str, str], list[dict[str, str]]]:
    path = download_cedict()
    pinyin_map: dict[str, str] = {}
    definition_map: dict[str, str] = {}
    entries: list[dict[str, str]] = []
    if not path:
        return pinyin_map, definition_map, entries

    line_re = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/$")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            match = line_re.match(line.strip())
            if not match:
                continue
            _trad, simplified, pinyin, definitions = match.groups()
            clean_defs = "; ".join(
                part for part in definitions.split("/") if part and "variant of" not in part.lower()
            )
            if not clean_defs:
                continue
            entries.append({"text": simplified, "pinyin": pinyin, "definition": clean_defs})
            if simplified not in definition_map:
                definition_map[simplified] = clean_defs
                pinyin_map[simplified] = pinyin
    return pinyin_map, definition_map, entries


def build_example_words(entries: list[dict[str, str]], characters: set[str]) -> dict[str, str]:
    examples: dict[str, list[str]] = {character: [] for character in characters}
    for char, words in EXAMPLE_WORD_OVERRIDES.items():
        if char in examples:
            examples[char].extend(f"{word} ({sentence_pinyin(word)})" for word in words[:3])
    blocked_definition_terms = (
        "variant of",
        "old variant",
        "archaic variant",
        "surname",
        "abbr.",
        "abbr for",
        "see ",
        "used in",
        "county",
        "district",
        "city",
        "province",
        "prefecture",
        "township",
        "village",
        "river",
        "mountain",
        "book of",
        "old name",
        "place name",
        "personal name",
        "transliteration",
        "loanword",
    )
    blocked_text_fragments = ("县", "区", "市", "省", "镇", "乡", "村", "路", "州", "书", "记")
    candidates: list[tuple[int, str, str]] = []
    for entry in entries:
        text = entry["text"]
        if not 2 <= len(text) <= 4:
            continue
        if not all(re.match(r"[\u4e00-\u9fff]", char) for char in text):
            continue
        definition = entry["definition"].lower()
        if any(term in definition for term in blocked_definition_terms):
            continue
        if any(fragment in text for fragment in blocked_text_fragments) and len(text) >= 3:
            continue
        # Prefer short, reusable words over idioms and proper-name-like entries.
        score = len(text)
        if len(text) == 2:
            score = 0
        elif len(text) == 3:
            score = 2
        candidates.append((score, text, entry["definition"]))

    for _score, text, _definition in sorted(candidates, key=lambda item: (item[0], len(item[1]), item[1])):
        for char in set(text):
            if char not in examples or len(examples[char]) >= 3:
                continue
            example = f"{text} ({sentence_pinyin(text)})"
            if example not in examples[char]:
                examples[char].append(example)
    return {char: "; ".join(words) for char, words in examples.items()}


def pinyin_for(text: str, cedict_pinyin: dict[str, str] | None = None) -> str:
    return sentence_pinyin(text)


def sentence_pinyin(text: str) -> str:
    chunks: list[str] = []
    buffer: list[str] = []
    ascii_buffer: list[str] = []

    def flush_buffer() -> None:
        if buffer:
            chunks.append(" ".join(lazy_pinyin("".join(buffer), style=Style.TONE)))
            buffer.clear()

    def flush_ascii() -> None:
        if ascii_buffer:
            chunks.append("".join(ascii_buffer))
            ascii_buffer.clear()

    punctuation = {
        "，": ",",
        "。": ".",
        "？": "?",
        "！": "!",
        "；": ";",
        "：": ":",
        "、": ",",
    }
    for char in text:
        if re.match(r"[\u4e00-\u9fff]", char):
            flush_ascii()
            buffer.append(char)
            continue
        flush_buffer()
        if char in punctuation:
            flush_ascii()
            chunks.append(punctuation[char])
        elif re.match(r"[A-Za-z0-9_-]", char):
            ascii_buffer.append(char)
        elif char.strip():
            flush_ascii()
            chunks.append(char)
        else:
            flush_ascii()
    flush_buffer()
    flush_ascii()

    output = " ".join(chunks)
    output = re.sub(r"\s+([,.?!;:])", r"\1", output)
    output = re.sub(r"([,.?!;:])(?=\S)", r"\1 ", output)
    return output.strip()


def assign_band(rank: float | int | None) -> str:
    if pd.isna(rank):
        return "Corpus/General Extension"
    rank_int = int(rank)
    if rank_int <= 100:
        return "Zero Beginner"
    if rank_int <= 150:
        return "HSK1 Core"
    if rank_int <= 300:
        return "HSK2 Expansion"
    if rank_int <= 600:
        return "HSK3 Expansion"
    if rank_int <= 3500:
        return "General 3500"
    if rank_int <= 7000:
        return "General 7000"
    return "Corpus/General Extension"


def frequency_tier(rank: float | int | None) -> str:
    if pd.isna(rank):
        return "No corpus rank"
    rank_int = int(rank)
    if rank_int <= 100:
        return "Top 100"
    if rank_int <= 300:
        return "Top 300"
    if rank_int <= 600:
        return "Top 600"
    if rank_int <= 1200:
        return "Top 1200"
    if rank_int <= 2500:
        return "Top 2500"
    return "Top 3500+"


def plain_pinyin(text: str) -> str:
    return " ".join(lazy_pinyin(text, style=Style.NORMAL))


def lookup_category(character: str, definition: object) -> str:
    for category, chars in LOOKUP_CATEGORIES.items():
        if character in chars:
            return category
    definition_text = str(definition).lower()
    keyword_map = [
        ("Business & Work", ("company", "business", "market", "money", "price", "work", "sell", "buy", "invoice", "contract")),
        ("People & Pronouns", ("person", "people", "father", "mother", "friend", "teacher", "student", "child", "son", "daughter")),
        ("Time", ("time", "day", "month", "year", "hour", "minute", "morning", "evening", "now", "later")),
        ("Places & Movement", ("place", "go", "come", "return", "road", "station", "city", "country", "inside", "outside")),
        ("Question & Function", ("particle", "question", "interjection", "negative prefix", "not", "also", "because", "therefore")),
        ("Actions", ("to ", "do", "make", "speak", "read", "write", "see", "hear", "eat", "drink")),
        ("Numbers & Measures", ("one", "two", "three", "number", "measure word", "classifier")),
    ]
    for category, keywords in keyword_map:
        if any(keyword in definition_text for keyword in keywords):
            return category
    return "General Reference"


def enrich_characters(
    df: pd.DataFrame,
    cedict_pinyin: dict[str, str],
    cedict_defs: dict[str, str],
    example_words: dict[str, str],
) -> pd.DataFrame:
    df = df.copy()
    df["pinyin"] = df["character"].map(lambda char: pinyin_for(char, cedict_pinyin))
    df["pinyin_plain"] = df["character"].map(plain_pinyin)
    df["pinyin_initial"] = df["pinyin_plain"].str[:1].str.upper()
    df["definition_en"] = df["character"].map(lambda char: cedict_defs.get(char, ""))
    df["example_words"] = df["character"].map(lambda char: example_words.get(char, ""))
    df["learning_band"] = df["frequency_rank"].map(assign_band)
    df["frequency_tier"] = df["frequency_rank"].map(frequency_tier)
    df["lookup_category"] = df.apply(lambda row: lookup_category(row["character"], row["definition_en"]), axis=1)
    df["source"] = df.apply(
        lambda row: ", ".join(
            label
            for label, included in [
                ("3500", row["in_3500"]),
                ("7000", row["in_7000"]),
                ("corpus", row["in_corpus"]),
            ]
            if included
        ),
        axis=1,
    )
    columns = [
        "character",
        "pinyin",
        "pinyin_plain",
        "pinyin_initial",
        "definition_en",
        "example_words",
        "lookup_category",
        "frequency_tier",
        "learning_band",
        "frequency_rank",
        "token",
        "frequency_per_million",
        "coverage_rate_pct",
        "rank_3500",
        "rank_7000",
        "in_3500",
        "in_7000",
        "in_corpus",
        "source",
    ]
    return df[columns]


def build_lessons(cedict_pinyin: dict[str, str]) -> list[dict[str, object]]:
    built = []
    for idx, lesson in enumerate(LESSONS, start=1):
        terms = [
            {
                "text": term.text,
                "pinyin": pinyin_for(term.text, cedict_pinyin),
                "meaning": term.meaning,
            }
            for term in lesson["terms"]
        ]
        sentences = [
            {
                "cn": sentence,
                "pinyin": sentence_pinyin(sentence),
                "en": meaning,
            }
            for sentence, meaning in lesson["sentences"]
        ]
        built.append(
            {
                "id": f"L{idx:02d}",
                "level": lesson["level"],
                "title": lesson["title"],
                "goal": lesson["goal"],
                "terms": terms,
                "sentences": sentences,
                "speaking_task": lesson["speaking_task"],
            }
        )
    return built


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_data(master: pd.DataFrame, lessons: list[dict[str, object]]) -> None:
    master.to_csv(PROCESSED / "characters_master.csv", index=False, encoding="utf-8-sig")
    learning = master[master["learning_band"].isin(["Zero Beginner", "HSK1 Core", "HSK2 Expansion", "HSK3 Expansion"])].copy()
    learning.to_csv(PROCESSED / "learning_characters.csv", index=False, encoding="utf-8-sig")
    common_3500 = master[master["in_3500"]].sort_values(["pinyin_plain", "frequency_rank", "rank_3500"], na_position="last").copy()
    common_3500.to_csv(PROCESSED / "common_3500_quick_reference.csv", index=False, encoding="utf-8-sig")
    common_3500.sort_values(["lookup_category", "frequency_rank", "pinyin_plain"], na_position="last").to_csv(
        PROCESSED / "common_3500_by_category.csv",
        index=False,
        encoding="utf-8-sig",
    )

    lesson_terms = []
    for lesson in lessons:
        for term in lesson["terms"]:
            lesson_terms.append(
                {
                    "lesson_id": lesson["id"],
                    "level": lesson["level"],
                    "lesson_title": lesson["title"],
                    **term,
                }
            )
    write_csv(
        PROCESSED / "lesson_vocabulary.csv",
        lesson_terms,
        ["lesson_id", "level", "lesson_title", "text", "pinyin", "meaning"],
    )
    write_csv(
        PROCESSED / "four_week_plan.csv",
        FOUR_WEEK_PLAN,
        ["week", "theme", "goals", "daily_routine", "deliverable"],
    )
    write_csv(
        PROCESSED / "speaking_drill_cards.csv",
        [
            {"prompt": prompt, "chinese": chinese, "english": english, "variation": variation, "pinyin": sentence_pinyin(chinese)}
            for prompt, chinese, english, variation in SPEAKING_DRILLS
        ],
        ["prompt", "chinese", "pinyin", "english", "variation"],
    )
    write_csv(
        PROCESSED / "business_phrasebook.csv",
        [
            {"scenario": scenario, "chinese": chinese, "pinyin": pinyin, "english": english}
            for scenario, chinese, english, pinyin in BUSINESS_PHRASES
        ],
        ["scenario", "chinese", "pinyin", "english"],
    )
    write_csv(
        PROCESSED / "placement_checklist.csv",
        [
            {"level": level, "can_do": can_do, "test_prompt": test_prompt}
            for level, can_do, test_prompt in PLACEMENT_CHECKLIST
        ],
        ["level", "can_do", "test_prompt"],
    )
    anki = learning.sort_values("frequency_rank", na_position="last").head(600).copy()
    anki_rows = [
        {
            "front": row.character,
            "back": f"{html.escape(str(row.pinyin))}<br>{html.escape(str(row.definition_en)[:180])}<br><small>{html.escape(str(row.example_words))}</small>",
            "tags": row.learning_band.replace(" ", "_").lower(),
        }
        for row in anki.itertuples()
    ]
    write_csv(PROCESSED / "anki_top_600.csv", anki_rows, ["front", "back", "tags"])
    (CONTENT / "lessons.json").write_text(json.dumps(lessons, ensure_ascii=False, indent=2), encoding="utf-8")
    (CONTENT / "product_packs.json").write_text(
        json.dumps([pack.__dict__ for pack in PRODUCT_PACKS], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    companion = {
        "four_week_plan": FOUR_WEEK_PLAN,
        "speaking_drills": [
            {"prompt": prompt, "chinese": chinese, "pinyin": sentence_pinyin(chinese), "english": english, "variation": variation}
            for prompt, chinese, english, variation in SPEAKING_DRILLS
        ],
        "business_phrases": [
            {"scenario": scenario, "chinese": chinese, "pinyin": pinyin, "english": english}
            for scenario, chinese, english, pinyin in BUSINESS_PHRASES
        ],
        "placement_checklist": [
            {"level": level, "can_do": can_do, "test_prompt": test_prompt}
            for level, can_do, test_prompt in PLACEMENT_CHECKLIST
        ],
    }
    (CONTENT / "learning_materials_companion.json").write_text(
        json.dumps(companion, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_pdf_fonts() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCustom",
            parent=base["Title"],
            fontName="STSong-Light",
            fontSize=24,
            leading=30,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "H1Custom",
            parent=base["Heading1"],
            fontName="STSong-Light",
            fontSize=17,
            leading=22,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "H2Custom",
            parent=base["Heading2"],
            fontName="STSong-Light",
            fontSize=13,
            leading=17,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "BodyCustom",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=9.5,
            leading=13,
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "SmallCustom",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8,
            leading=10,
        ),
    }


def p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape("" if text is None else str(text)), style)


def add_table(story: list[object], rows: list[list[object]], widths: list[float], style: ParagraphStyle) -> None:
    table_rows = [[p(cell, style) for cell in row] for row in rows]
    table = Table(table_rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#203040")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c7ccd1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))


def build_study_pack(lessons: list[dict[str, object]]) -> None:
    register_pdf_fonts()
    st = styles()
    doc = SimpleDocTemplate(
        str(PDF / "Chinese_Character_Content_Study_Pack.pdf"),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Chinese Character Content Study Pack",
    )
    story: list[object] = [
        p("Chinese Character Content", st["title"]),
        p("Speaking-first materials for English-speaking beginners, HSK 1-3 learners, and business Chinese starters.", st["body"]),
        Spacer(1, 6 * mm),
        p("How to Use", st["h1"]),
        p("1. Read the words aloud. 2. Practice the sentence patterns. 3. Complete the speaking task without looking. Writing and stroke order are intentionally excluded in this version.", st["body"]),
        PageBreak(),
    ]

    current_level = None
    for lesson in lessons:
        if current_level != lesson["level"]:
            if current_level is not None:
                story.append(PageBreak())
            current_level = lesson["level"]
            story.append(p(str(current_level), st["h1"]))
        story.append(p(f"{lesson['id']} - {lesson['title']}", st["h2"]))
        story.append(p(f"Goal: {lesson['goal']}", st["body"]))
        vocab_rows = [["Chinese", "Pinyin", "English"]] + [
            [term["text"], term["pinyin"], term["meaning"]] for term in lesson["terms"]
        ]
        add_table(story, vocab_rows, [35 * mm, 55 * mm, 78 * mm], st["small"])
        sentence_rows = [["Chinese", "Pinyin", "English"]] + [
            [sent["cn"], sent["pinyin"], sent["en"]] for sent in lesson["sentences"]
        ]
        add_table(story, sentence_rows, [55 * mm, 65 * mm, 48 * mm], st["small"])
        story.append(p(f"Speaking task: {lesson['speaking_task']}", st["body"]))
        story.append(Spacer(1, 7 * mm))
    doc.build(story)


def build_character_pdf(master: pd.DataFrame) -> None:
    register_pdf_fonts()
    st = styles()
    doc = SimpleDocTemplate(
        str(PDF / "Master_Character_List_Top_600.pdf"),
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Master Character List Top 600",
    )
    story: list[object] = [
        p("Master Character List: Top 600", st["title"]),
        p("Characters are ranked by the 2.5-billion-character corpus frequency file, then grouped into HSK-inspired learning bands.", st["body"]),
        Spacer(1, 5 * mm),
    ]
    top = master[master["frequency_rank"].notna()].sort_values("frequency_rank").head(600)
    for band, group in top.groupby("learning_band", sort=False):
        story.append(p(str(band), st["h1"]))
        rows = [["Rank", "字", "Pinyin", "English"]] + [
            [
                int(row.frequency_rank),
                row.character,
                row.pinyin,
                str(row.definition_en)[:120],
            ]
            for row in group.itertuples()
        ]
        add_table(story, rows, [17 * mm, 15 * mm, 38 * mm, 103 * mm], st["small"])
    doc.build(story)


def build_common_3500_pdf(master: pd.DataFrame) -> None:
    register_pdf_fonts()
    st = styles()
    doc = SimpleDocTemplate(
        str(PDF / "Common_3500_Character_Quick_Reference.pdf"),
        pagesize=A4,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="Common 3500 Character Quick Reference",
    )
    common = master[master["in_3500"]].sort_values(["pinyin_plain", "frequency_rank", "rank_3500"], na_position="last")
    story: list[object] = [
        p("Common 3500 Character Quick Reference", st["title"]),
        p("A foreign-learner lookup reference sorted by pinyin. Use browser/PDF search for fast lookup by character, pinyin, or English meaning.", st["body"]),
        Spacer(1, 4 * mm),
    ]
    for initial, group in common.groupby("pinyin_initial", sort=True):
        story.append(p(str(initial), st["h1"]))
        rows = [["字", "Pinyin", "English", "Examples", "Category", "Freq"]] + [
            [
                row.character,
                row.pinyin,
                str(row.definition_en)[:80],
                str(row.example_words)[:58],
                row.lookup_category,
                "" if pd.isna(row.frequency_rank) else int(row.frequency_rank),
            ]
            for row in group.itertuples()
        ]
        add_table(story, rows, [11 * mm, 25 * mm, 61 * mm, 45 * mm, 27 * mm, 10 * mm], st["small"])
    doc.build(story)


def build_product_packs_pdf() -> None:
    register_pdf_fonts()
    st = styles()
    doc = SimpleDocTemplate(
        str(PDF / "Sellable_Learning_Packs.pdf"),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Sellable Learning Packs",
    )
    story: list[object] = [
        p("Sellable Learning Packs", st["title"]),
        p("Product angles built from the same character database, designed for English-speaking learners and practical speaking outcomes.", st["body"]),
        Spacer(1, 5 * mm),
    ]
    for pack in PRODUCT_PACKS:
        story.append(p(pack.title, st["h1"]))
        rows = [
            ["Audience", pack.audience],
            ["Promise", pack.promise],
            ["Deliverables", "; ".join(pack.deliverables)],
            ["Sample topics", "; ".join(pack.sample_topics)],
            ["Why it sells", pack.why_it_sells],
        ]
        add_table(story, rows, [33 * mm, 135 * mm], st["small"])
    doc.build(story)


def build_learning_materials_pdf() -> None:
    register_pdf_fonts()
    st = styles()
    doc = SimpleDocTemplate(
        str(PDF / "Learning_Materials_Companion.pdf"),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Learning Materials Companion",
    )
    story: list[object] = [
        p("Learning Materials Companion", st["title"]),
        p("Teacher-ready and learner-ready documents for using the character data as a short speaking course.", st["body"]),
        Spacer(1, 5 * mm),
        p("Teacher Guide", st["h1"]),
        p("Use each lesson as a 30-45 minute session: warm-up with 5 characters, model pronunciation, drill sentence patterns, run pair practice, then record a short speaking task. Do not require handwriting in this version; the learning goal is recognition, pronunciation, and usable speech.", st["body"]),
        p("Learner Guide", st["h1"]),
        p("Study in short daily sessions. Read the Chinese aloud, cover the English, speak the sentence from memory, then replace one word with your own information. Use the 3500 Finder when you meet an unknown character.", st["body"]),
        p("4-Week Learning Plan", st["h1"]),
    ]
    add_table(
        story,
        [["Week", "Theme", "Goals", "Daily Routine", "Deliverable"]]
        + [[item["week"], item["theme"], item["goals"], item["daily_routine"], item["deliverable"]] for item in FOUR_WEEK_PLAN],
        [17 * mm, 32 * mm, 44 * mm, 48 * mm, 35 * mm],
        st["small"],
    )
    story.append(PageBreak())
    story.append(p("Speaking Drill Cards", st["h1"]))
    add_table(
        story,
        [["Prompt", "Chinese", "Pinyin", "English", "Variation"]]
        + [[prompt, chinese, sentence_pinyin(chinese), english, variation] for prompt, chinese, english, variation in SPEAKING_DRILLS],
        [34 * mm, 39 * mm, 38 * mm, 42 * mm, 25 * mm],
        st["small"],
    )
    story.append(PageBreak())
    story.append(p("Business Phrasebook", st["h1"]))
    add_table(
        story,
        [["Scenario", "Chinese", "Pinyin", "English"]]
        + [[scenario, chinese, pinyin, english] for scenario, chinese, english, pinyin in BUSINESS_PHRASES],
        [35 * mm, 48 * mm, 55 * mm, 40 * mm],
        st["small"],
    )
    story.append(p("Placement Checklist", st["h1"]))
    add_table(
        story,
        [["Level", "Can-do Statement", "Test Prompt"]]
        + [[level, can_do, test_prompt] for level, can_do, test_prompt in PLACEMENT_CHECKLIST],
        [30 * mm, 82 * mm, 64 * mm],
        st["small"],
    )
    doc.build(story)


def html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="assets/styles.css">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="index.html">Chinese Character Content</a>
    <nav>
      <a href="index.html#lessons">Lessons</a>
      <a href="characters.html">Top 600</a>
      <a href="common-3500.html">3500 Finder</a>
      <a href="materials.html">Materials</a>
      <a href="packs.html">Packs</a>
      <a href="downloads.html">Downloads</a>
    </nav>
  </header>
  <main>
{body}
  </main>
</body>
</html>
"""


def lesson_card(lesson: dict[str, object]) -> str:
    vocab_rows = "\n".join(
        f"<tr><td class='han'>{html.escape(term['text'])}</td><td>{html.escape(term['pinyin'])}</td><td>{html.escape(term['meaning'])}</td></tr>"
        for term in lesson["terms"]
    )
    sentence_rows = "\n".join(
        f"<tr><td>{html.escape(sent['cn'])}</td><td>{html.escape(sent['pinyin'])}</td><td>{html.escape(sent['en'])}</td></tr>"
        for sent in lesson["sentences"]
    )
    return f"""
    <article class="lesson">
      <div class="lesson-head">
        <span>{html.escape(lesson['id'])}</span>
        <h3>{html.escape(lesson['title'])}</h3>
      </div>
      <p class="goal">{html.escape(lesson['goal'])}</p>
      <h4>Vocabulary</h4>
      <table><thead><tr><th>Chinese</th><th>Pinyin</th><th>English</th></tr></thead><tbody>{vocab_rows}</tbody></table>
      <h4>Sentences</h4>
      <table><thead><tr><th>Chinese</th><th>Pinyin</th><th>English</th></tr></thead><tbody>{sentence_rows}</tbody></table>
      <p class="task"><strong>Speaking task:</strong> {html.escape(lesson['speaking_task'])}</p>
    </article>
    """


def build_site(master: pd.DataFrame, lessons: list[dict[str, object]]) -> None:
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    css = """
:root {
  color-scheme: light;
  --ink: #18212b;
  --muted: #5f6b7a;
  --line: #d7dce2;
  --paper: #ffffff;
  --band: #f3f6f8;
  --accent: #0f766e;
  --accent-dark: #134e4a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: #fbfcfd;
  line-height: 1.5;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 14px 28px;
  background: rgba(255,255,255,0.96);
  border-bottom: 1px solid var(--line);
}
.brand { color: var(--accent-dark); font-weight: 760; text-decoration: none; }
nav { display: flex; gap: 16px; flex-wrap: wrap; }
nav a { color: var(--ink); text-decoration: none; font-size: 14px; }
main { max-width: 1120px; margin: 0 auto; padding: 32px 24px 56px; }
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.7fr);
  gap: 32px;
  align-items: end;
  border-bottom: 1px solid var(--line);
  padding-bottom: 26px;
}
h1 { font-size: clamp(34px, 5vw, 62px); line-height: 1.02; margin: 0 0 16px; letter-spacing: 0; }
h2 { margin: 34px 0 12px; font-size: 26px; }
h3 { margin: 0; font-size: 20px; }
h4 { margin: 18px 0 8px; font-size: 14px; color: var(--accent-dark); text-transform: uppercase; }
.lead { font-size: 18px; color: var(--muted); max-width: 760px; }
.stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.stat { background: var(--band); border: 1px solid var(--line); padding: 14px; border-radius: 8px; }
.stat strong { display: block; font-size: 24px; color: var(--accent-dark); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }
.tile, .lesson {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
}
.tile p, .goal { color: var(--muted); margin-bottom: 0; }
.lesson { margin: 18px 0; }
.lesson-head { display: flex; gap: 12px; align-items: baseline; }
.lesson-head span {
  color: white;
  background: var(--accent);
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 12px;
  font-weight: 700;
}
table { width: 100%; border-collapse: collapse; font-size: 14px; margin: 8px 0 14px; }
th, td { border: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #203040; color: white; font-weight: 680; }
tbody tr:nth-child(even) { background: #f8fafb; }
.han { font-size: 20px; font-weight: 720; }
.task { border-left: 4px solid var(--accent); padding-left: 12px; }
.downloads a { display: block; margin: 8px 0; color: var(--accent-dark); font-weight: 700; }
.anchors { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }
.anchors a {
  min-width: 32px;
  text-align: center;
  text-decoration: none;
  color: var(--accent-dark);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 7px;
  background: white;
}
.badge {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--accent-dark);
  background: var(--band);
  font-size: 12px;
}
.pack-meta { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.finder-tools {
  position: sticky;
  top: 58px;
  z-index: 5;
  background: rgba(251,252,253,0.97);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  margin: 18px 0;
}
.finder-row { display: grid; grid-template-columns: 1.4fr 0.8fr; gap: 10px; }
.finder-tools input, .finder-tools select {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
  background: white;
}
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.filters button {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 7px 10px;
  color: var(--ink);
  background: white;
  cursor: pointer;
}
.filters button.active { color: white; background: var(--accent-dark); border-color: var(--accent-dark); }
.finder-count { color: var(--muted); margin: 10px 0 0; font-size: 14px; }
.finder-section { margin: 14px 0; border: 1px solid var(--line); border-radius: 8px; background: white; }
.finder-section summary { cursor: pointer; padding: 13px 16px; font-weight: 760; color: var(--accent-dark); }
.finder-section table { margin: 0; border-left: 0; border-right: 0; border-bottom: 0; }
.char-row.hidden { display: none; }
.examples { color: var(--muted); font-size: 13px; }
@media (max-width: 760px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  .hero { grid-template-columns: 1fr; }
  main { padding: 24px 14px 42px; }
  table { font-size: 13px; }
  th, td { padding: 7px; }
  .finder-tools { top: 104px; }
  .finder-row { grid-template-columns: 1fr; }
}
"""
    (SITE / "assets" / "styles.css").write_text(css, encoding="utf-8")

    level_counts = master["learning_band"].value_counts().to_dict()
    total_chars = len(master)
    lesson_count = len(lessons)
    terms_count = sum(len(lesson["terms"]) for lesson in lessons)
    levels = ["Zero Beginner", "HSK1 Core", "HSK2 Expansion", "HSK3 Expansion", "Business Starter"]
    level_tiles = "\n".join(
        f"<section class='tile'><h3>{html.escape(level)}</h3><p>{sum(1 for lesson in lessons if lesson['level'] == level)} lessons. Character band count: {level_counts.get(level, 0)}.</p></section>"
        for level in levels
    )
    lesson_sections = []
    for level in levels:
        cards = "\n".join(lesson_card(lesson) for lesson in lessons if lesson["level"] == level)
        lesson_sections.append(f"<section id='{html.escape(level.lower().replace(' ', '-'))}'><h2>{html.escape(level)}</h2>{cards}</section>")

    index_body = f"""
    <section class="hero">
      <div>
        <h1>Speaking-first Chinese character materials</h1>
        <p class="lead">Printable and web-ready lessons for English-speaking beginners, HSK 1-3 learners, and business Chinese starters. The character sequence is driven by local frequency data and common-character lists.</p>
      </div>
      <div class="stats">
        <div class="stat"><strong>{total_chars:,}</strong><span>merged characters</span></div>
        <div class="stat"><strong>600</strong><span>top learning characters</span></div>
        <div class="stat"><strong>{lesson_count}</strong><span>speaking lessons</span></div>
        <div class="stat"><strong>{terms_count}</strong><span>lesson terms</span></div>
      </div>
    </section>
    <section>
      <h2>New Product Angles</h2>
      <div class="grid">
        <section class="tile"><h3>3500 Character Finder</h3><p>A pinyin-first quick reference for foreign learners, with English meanings, frequency ranks, and learner-friendly categories.</p></section>
        <section class="tile"><h3>Business Trip Kit</h3><p>A workplace-focused learning pack for introductions, meetings, follow-up messages, prices, and payment.</p></section>
        <section class="tile"><h3>HSK Speaking Bridge</h3><p>Exam-oriented foundations turned into spoken sentence patterns and short oral tasks.</p></section>
        <section class="tile"><h3>Teacher-Ready Materials</h3><p>4-week plan, speaking drill cards, placement checklist, business phrasebook, and Anki/Quizlet CSV exports.</p></section>
      </div>
    </section>
    <section>
      <h2>Learning Tracks</h2>
      <div class="grid">{level_tiles}</div>
    </section>
    <section id="lessons">
      <h2>Lessons</h2>
      {''.join(lesson_sections)}
    </section>
"""
    (SITE / "index.html").write_text(html_page("Chinese Character Content", index_body), encoding="utf-8")

    top = master[master["frequency_rank"].notna()].sort_values("frequency_rank").head(600)
    char_rows = "\n".join(
        f"<tr><td>{int(row.frequency_rank)}</td><td class='han'>{html.escape(row.character)}</td><td>{html.escape(row.pinyin)}</td><td>{html.escape(row.learning_band)}</td><td>{html.escape(str(row.definition_en)[:160])}</td></tr>"
        for row in top.itertuples()
    )
    char_body = f"""
    <h1>Top 600 Characters</h1>
    <p class="lead">Ranked by corpus frequency and grouped into HSK-inspired learning bands.</p>
    <table>
      <thead><tr><th>Rank</th><th>Character</th><th>Pinyin</th><th>Band</th><th>English</th></tr></thead>
      <tbody>{char_rows}</tbody>
    </table>
"""
    (SITE / "characters.html").write_text(html_page("Top 600 Characters", char_body), encoding="utf-8")

    common_3500 = master[master["in_3500"]].sort_values(["pinyin_plain", "frequency_rank", "rank_3500"], na_position="last")
    anchors = "\n".join(
        f"<a href='#{html.escape(initial)}'>{html.escape(initial)}</a>"
        for initial in common_3500["pinyin_initial"].dropna().drop_duplicates()
    )
    category_options = "\n".join(
        f"<option value='{html.escape(category)}'>{html.escape(category)}</option>"
        for category in sorted(common_3500["lookup_category"].dropna().unique())
    )
    groups = []
    for initial, group in common_3500.groupby("pinyin_initial", sort=True):
        rows = "\n".join(
            f"""<tr class="char-row" data-search="{html.escape(' '.join([row.character, row.pinyin, row.pinyin_plain, str(row.definition_en), str(row.example_words), row.lookup_category]).lower())}" data-category="{html.escape(row.lookup_category)}" data-rank="{'' if pd.isna(row.frequency_rank) else int(row.frequency_rank)}">
              <td class='han'>{html.escape(row.character)}</td>
              <td>{html.escape(row.pinyin)}</td>
              <td>{html.escape(str(row.definition_en)[:180])}</td>
              <td class="examples">{html.escape(str(row.example_words))}</td>
              <td>{html.escape(row.lookup_category)}</td>
              <td>{'' if pd.isna(row.frequency_rank) else int(row.frequency_rank)}</td>
              <td>{int(row.rank_3500)}</td>
            </tr>"""
            for row in group.itertuples()
        )
        groups.append(
            f"""
            <details class="finder-section" id="{html.escape(initial)}" open>
              <summary>{html.escape(initial)}</summary>
              <table>
                <thead><tr><th>字</th><th>Pinyin</th><th>English</th><th>Examples</th><th>Category</th><th>Freq</th><th>3500</th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </details>
            """
        )
    common_body = f"""
    <h1>3500 Character Finder</h1>
    <p class="lead">A pinyin-first quick reference for foreign learners. Search by character, pinyin, English meaning, category, or example word.</p>
    <section class="finder-tools" aria-label="3500 character filters">
      <div class="finder-row">
        <input id="finderSearch" type="search" placeholder="Search: ni hao, meeting, 我, business..." autocomplete="off">
        <select id="categoryFilter">
          <option value="all">All categories</option>
          {category_options}
        </select>
      </div>
      <div class="filters" aria-label="Frequency filters">
        <button type="button" class="active" data-rank="all">All 3500</button>
        <button type="button" data-rank="100">Top 100</button>
        <button type="button" data-rank="300">Top 300</button>
        <button type="button" data-rank="600">Top 600</button>
        <button type="button" data-rank="1200">Top 1200</button>
        <button type="button" data-rank="2500">Top 2500</button>
      </div>
      <p class="finder-count"><span id="visibleCount">3500</span> of 3500 characters shown</p>
    </section>
    <div class="anchors">{anchors}</div>
    {''.join(groups)}
    <script>
      const rows = Array.from(document.querySelectorAll('.char-row'));
      const searchInput = document.getElementById('finderSearch');
      const categoryFilter = document.getElementById('categoryFilter');
      const count = document.getElementById('visibleCount');
      let rankLimit = 'all';

      function applyFilters() {{
        const query = searchInput.value.trim().toLowerCase();
        const category = categoryFilter.value;
        let visible = 0;
        rows.forEach((row) => {{
          const rank = Number(row.dataset.rank || 999999);
          const matchesSearch = !query || row.dataset.search.includes(query);
          const matchesCategory = category === 'all' || row.dataset.category === category;
          const matchesRank = rankLimit === 'all' || rank <= Number(rankLimit);
          const show = matchesSearch && matchesCategory && matchesRank;
          row.classList.toggle('hidden', !show);
          if (show) visible += 1;
        }});
        document.querySelectorAll('.finder-section').forEach((section) => {{
          const hasVisible = Boolean(section.querySelector('.char-row:not(.hidden)'));
          section.style.display = hasVisible ? '' : 'none';
          if (query || category !== 'all' || rankLimit !== 'all') section.open = true;
        }});
        count.textContent = String(visible);
      }}

      searchInput.addEventListener('input', applyFilters);
      categoryFilter.addEventListener('change', applyFilters);
      document.querySelectorAll('.filters button[data-rank]').forEach((button) => {{
        button.addEventListener('click', () => {{
          rankLimit = button.dataset.rank;
          document.querySelectorAll('.filters button[data-rank]').forEach((item) => item.classList.remove('active'));
          button.classList.add('active');
          applyFilters();
        }});
      }});
    </script>
"""
    (SITE / "common-3500.html").write_text(html_page("3500 Character Finder", common_body), encoding="utf-8")

    pack_cards = "\n".join(
        f"""
        <article class="lesson">
          <div class="lesson-head"><span>{html.escape(pack.slug)}</span><h3>{html.escape(pack.title)}</h3></div>
          <p class="goal">{html.escape(pack.promise)}</p>
          <div class="pack-meta"><span class="badge">{html.escape(pack.audience)}</span></div>
          <table>
            <tbody>
              <tr><th>Deliverables</th><td>{html.escape('; '.join(pack.deliverables))}</td></tr>
              <tr><th>Sample topics</th><td>{html.escape('; '.join(pack.sample_topics))}</td></tr>
              <tr><th>Why it sells</th><td>{html.escape(pack.why_it_sells)}</td></tr>
            </tbody>
          </table>
        </article>
        """
        for pack in PRODUCT_PACKS
    )
    category_counts = master[master["in_3500"]]["lookup_category"].value_counts().sort_index()
    category_rows = "\n".join(
        f"<tr><td>{html.escape(category)}</td><td>{count}</td><td>{html.escape(', '.join(master[(master['in_3500']) & (master['lookup_category'] == category)].sort_values('frequency_rank', na_position='last').head(12)['character'].tolist()))}</td></tr>"
        for category, count in category_counts.items()
    )
    packs_body = f"""
    <h1>Productized Learning Packs</h1>
    <p class="lead">These are sellable content directions built from the same data foundation: fast speaking wins, workplace utility, HSK support, and a foreign-learner 3500-character reference.</p>
    <section>{pack_cards}</section>
    <section>
      <h2>3500 Character Categories</h2>
      <table>
        <thead><tr><th>Category</th><th>Characters</th><th>High-frequency examples</th></tr></thead>
        <tbody>{category_rows}</tbody>
      </table>
    </section>
"""
    (SITE / "packs.html").write_text(html_page("Productized Learning Packs", packs_body), encoding="utf-8")

    plan_rows = "\n".join(
        f"<tr><td>{html.escape(item['week'])}</td><td>{html.escape(item['theme'])}</td><td>{html.escape(item['goals'])}</td><td>{html.escape(item['daily_routine'])}</td><td>{html.escape(item['deliverable'])}</td></tr>"
        for item in FOUR_WEEK_PLAN
    )
    drill_rows = "\n".join(
        f"<tr><td>{html.escape(prompt)}</td><td class='han'>{html.escape(chinese)}</td><td>{html.escape(sentence_pinyin(chinese))}</td><td>{html.escape(english)}</td><td>{html.escape(variation)}</td></tr>"
        for prompt, chinese, english, variation in SPEAKING_DRILLS
    )
    business_rows = "\n".join(
        f"<tr><td>{html.escape(scenario)}</td><td class='han'>{html.escape(chinese)}</td><td>{html.escape(pinyin)}</td><td>{html.escape(english)}</td></tr>"
        for scenario, chinese, english, pinyin in BUSINESS_PHRASES
    )
    placement_rows = "\n".join(
        f"<tr><td>{html.escape(level)}</td><td>{html.escape(can_do)}</td><td>{html.escape(test_prompt)}</td></tr>"
        for level, can_do, test_prompt in PLACEMENT_CHECKLIST
    )
    materials_body = f"""
    <h1>Learning Materials</h1>
    <p class="lead">Teacher-ready and learner-ready companion materials built around speaking practice, HSK 1-3 foundations, and business starter use cases.</p>
    <section class="grid">
      <article class="tile"><h3>Teacher Guide</h3><p>Run each lesson as a 30-45 minute class: character warm-up, pronunciation model, sentence substitution, pair role-play, and one recorded speaking task.</p></article>
      <article class="tile"><h3>Learner Guide</h3><p>Study in short daily sessions: read aloud, cover English, speak from memory, then substitute your own name, country, job, time, or company.</p></article>
      <article class="tile"><h3>Assessment</h3><p>Use the placement checklist to decide whether a learner should start at Zero Beginner, HSK1, HSK2, HSK3, or Business Starter.</p></article>
    </section>
    <section>
      <h2>4-Week Learning Plan</h2>
      <table><thead><tr><th>Week</th><th>Theme</th><th>Goals</th><th>Daily Routine</th><th>Deliverable</th></tr></thead><tbody>{plan_rows}</tbody></table>
    </section>
    <section>
      <h2>Speaking Drill Cards</h2>
      <table><thead><tr><th>Prompt</th><th>Chinese</th><th>Pinyin</th><th>English</th><th>Variation</th></tr></thead><tbody>{drill_rows}</tbody></table>
    </section>
    <section>
      <h2>Business Phrasebook</h2>
      <table><thead><tr><th>Scenario</th><th>Chinese</th><th>Pinyin</th><th>English</th></tr></thead><tbody>{business_rows}</tbody></table>
    </section>
    <section>
      <h2>Placement Checklist</h2>
      <table><thead><tr><th>Level</th><th>Can-do Statement</th><th>Test Prompt</th></tr></thead><tbody>{placement_rows}</tbody></table>
    </section>
"""
    (SITE / "materials.html").write_text(html_page("Learning Materials", materials_body), encoding="utf-8")

    files_root = SITE / "files"
    for folder in [files_root / "pdf", files_root / "data", files_root / "content"]:
        folder.mkdir(parents=True, exist_ok=True)
    for source in PDF.glob("*.pdf"):
        shutil.copy2(source, files_root / "pdf" / source.name)
    for source in PROCESSED.glob("*.csv"):
        shutil.copy2(source, files_root / "data" / source.name)
    shutil.copy2(CONTENT / "lessons.json", files_root / "content" / "lessons.json")
    shutil.copy2(CONTENT / "product_packs.json", files_root / "content" / "product_packs.json")
    shutil.copy2(CONTENT / "learning_materials_companion.json", files_root / "content" / "learning_materials_companion.json")

    downloads_body = """
    <h1>Downloads</h1>
    <section class="downloads">
      <h2>PDF</h2>
      <a href="files/pdf/Chinese_Character_Content_Study_Pack.pdf">Chinese Character Content Study Pack</a>
      <a href="files/pdf/Master_Character_List_Top_600.pdf">Master Character List Top 600</a>
      <a href="files/pdf/Common_3500_Character_Quick_Reference.pdf">Common 3500 Character Quick Reference</a>
      <a href="files/pdf/Sellable_Learning_Packs.pdf">Sellable Learning Packs</a>
      <a href="files/pdf/Learning_Materials_Companion.pdf">Learning Materials Companion</a>
      <h2>Data</h2>
      <a href="files/data/characters_master.csv">Characters master CSV</a>
      <a href="files/data/learning_characters.csv">Learning characters CSV</a>
      <a href="files/data/lesson_vocabulary.csv">Lesson vocabulary CSV</a>
      <a href="files/data/common_3500_quick_reference.csv">Common 3500 quick reference CSV</a>
      <a href="files/data/common_3500_by_category.csv">Common 3500 by category CSV</a>
      <a href="files/data/four_week_plan.csv">4-week learning plan CSV</a>
      <a href="files/data/speaking_drill_cards.csv">Speaking drill cards CSV</a>
      <a href="files/data/business_phrasebook.csv">Business phrasebook CSV</a>
      <a href="files/data/placement_checklist.csv">Placement checklist CSV</a>
      <a href="files/data/anki_top_600.csv">Anki / Quizlet top 600 CSV</a>
      <a href="files/content/lessons.json">Lessons JSON</a>
      <a href="files/content/product_packs.json">Product packs JSON</a>
      <a href="files/content/learning_materials_companion.json">Learning materials companion JSON</a>
      <h2>Attribution</h2>
      <p>English definitions are derived from CC-CEDICT via MDBG and are shared under CC BY-SA 4.0 attribution-sharealike terms.</p>
      <a href="https://www.mdbg.net/chinese/dictionary?page=cc-cedict">CC-CEDICT at MDBG</a>
      <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>
    </section>
"""
    (SITE / "downloads.html").write_text(html_page("Downloads", downloads_body), encoding="utf-8")


def write_summary(master: pd.DataFrame, lessons: list[dict[str, object]]) -> None:
    summary = {
        "merged_characters": int(len(master)),
        "source_counts": {
            "3500": int(master["in_3500"].sum()),
            "7000": int(master["in_7000"].sum()),
            "corpus": int(master["in_corpus"].sum()),
        },
        "top_600_characters": 600,
        "lessons": len(lessons),
        "lesson_terms": sum(len(lesson["terms"]) for lesson in lessons),
        "outputs": [
            "data/processed/characters_master.csv",
            "data/processed/learning_characters.csv",
            "data/processed/lesson_vocabulary.csv",
            "data/processed/common_3500_quick_reference.csv",
            "data/processed/common_3500_by_category.csv",
            "data/processed/four_week_plan.csv",
            "data/processed/speaking_drill_cards.csv",
            "data/processed/business_phrasebook.csv",
            "data/processed/placement_checklist.csv",
            "data/processed/anki_top_600.csv",
            "content/lessons.json",
            "content/product_packs.json",
            "content/learning_materials_companion.json",
            "pdf/Chinese_Character_Content_Study_Pack.pdf",
            "pdf/Master_Character_List_Top_600.pdf",
            "pdf/Common_3500_Character_Quick_Reference.pdf",
            "pdf/Sellable_Learning_Packs.pdf",
            "pdf/Learning_Materials_Companion.pdf",
            "docs/index.html",
            "docs/common-3500.html",
            "docs/packs.html",
            "docs/materials.html",
        ],
    }
    (PROCESSED / "build_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    ensure_dirs()
    cedict_pinyin, cedict_defs, cedict_entries = load_cedict()
    source = read_source_data()
    example_words = build_example_words(cedict_entries, set(source["character"]))
    master = enrich_characters(source, cedict_pinyin, cedict_defs, example_words)
    lessons = build_lessons(cedict_pinyin)
    export_data(master, lessons)
    build_study_pack(lessons)
    build_character_pdf(master)
    build_common_3500_pdf(master)
    build_product_packs_pdf()
    build_learning_materials_pdf()
    build_site(master, lessons)
    write_summary(master, lessons)
    print(f"Done. Merged {len(master):,} characters and built {len(lessons)} lessons.")


if __name__ == "__main__":
    main()
