import unittest

from crawler.parsing import (
    parse_platform_average_views,
    parse_threshold_engagement_rate,
    parse_threshold_views,
    row_to_accounts,
)


HEADERS = [
    "序号",
    "分类",
    "外网账号（平台 + 名称）",
    "原账号 2026 官方身份",
    "2026 平台单条平均阅读量",
    "雷达号名称",
    "雷达号专属人设简介",
    "内容筛选门槛（贴合平均值）",
]


class ParsingTests(unittest.TestCase):
    def test_parse_thresholds(self):
        self.assertEqual(parse_threshold_views("单条阅读≥50 万，互动率≥1.5%"), 500000)
        self.assertEqual(parse_threshold_engagement_rate("单条阅读≥50 万，互动率≥1.5%"), 0.015)

    def test_parse_platform_specific_average(self):
        text = "X 平台 60 万 / YouTube 平台 80 万"
        self.assertEqual(parse_platform_average_views(text, "x"), 600000)
        self.assertEqual(parse_platform_average_views(text, "youtube"), 800000)

    def test_multi_platform_row_splits_accounts(self):
        row = (
            31,
            "商业创业实战",
            "X/YouTube-Alex Hormozi",
            "Acquisition.com创始人",
            "X 平台 60 万 / YouTube 平台 80 万",
            "Hormozi 商业实战圈",
            "专注商业实战",
            "单条阅读≥50 万，互动率≥1.5%",
        )
        accounts = row_to_accounts(HEADERS, row, 32)
        self.assertEqual([account.platform for account in accounts], ["x", "youtube"])
        self.assertEqual([account.average_views for account in accounts], [600000, 800000])
        self.assertEqual(accounts[0].threshold_views, 500000)

    def test_detects_instagram_youtube_mismatch(self):
        row = (
            33,
            "商业创业实战",
            "X/Instagram-Grant Cardone",
            "Cardone Capital 创始人",
            "X 平台 55 万 / YouTube 平台 75 万",
            "卡登销售与财富",
            "专注销售",
            "单条阅读≥50 万，互动率≥1.5%",
        )
        accounts = row_to_accounts(HEADERS, row, 34)
        self.assertTrue(any("Instagram" in account.data_quality_issue for account in accounts))


if __name__ == "__main__":
    unittest.main()
