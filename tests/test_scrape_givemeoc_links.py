import unittest

from tools.scrape_givemeoc_links import extract_jobs, extract_max_page, dedupe_jobs


SAMPLE_HTML = """
<html>
  <body>
    <div class="crt-pagination">
      <a href="?paged=2" class="crt-page-link">2</a>
      <a href="?paged=220" class="crt-page-link">220</a>
    </div>
    <table>
      <tbody id="crt-companies-tbody">
        <tr data-id="21370">
          <td class="crt-col-company">摩根士丹利证券</td>
          <td class="crt-col-type"><span>外企</span></td>
          <td class="crt-col-company">外企,银行/金融</td>
          <td class="crt-col-recruitment-type"><span>实习</span></td>
          <td class="crt-col-target"><span>2028届</span></td>
          <td class="crt-col-location">北京,上海</td>
          <td class="crt-col-position"><span class="crt-position-tag">暑期实习生\\专业不限</span></td>
          <td class="crt-col-status"><span>未投递</span></td>
          <td class="crt-col-update-time">2026-07-07</td>
          <td class="crt-col-deadline">2026-10-07</td>
          <td class="crt-col-links">
            <a href="https://example.com/apply" class="crt-link">投递</a>
          </td>
          <td class="crt-col-notice">
            <a href="https://mp.weixin.qq.com/s/example" class="crt-link crt-notice-link">公告</a>
          </td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""


class ScrapeGivemeocLinksTests(unittest.TestCase):
    def test_extract_max_page_from_pagination_links(self):
        self.assertEqual(extract_max_page(SAMPLE_HTML), 220)

    def test_extract_jobs_reads_public_table_fields(self):
        jobs = extract_jobs(SAMPLE_HTML, page=1)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_id"], "21370")
        self.assertEqual(jobs[0]["company"], "摩根士丹利证券")
        self.assertEqual(jobs[0]["company_type"], "外企")
        self.assertEqual(jobs[0]["industry"], "外企,银行/金融")
        self.assertEqual(jobs[0]["recruitment_type"], "实习")
        self.assertEqual(jobs[0]["target_candidates"], "2028届")
        self.assertEqual(jobs[0]["location"], "北京,上海")
        self.assertEqual(jobs[0]["position"], "暑期实习生\\专业不限")
        self.assertEqual(jobs[0]["updated_at"], "2026-07-07")
        self.assertEqual(jobs[0]["deadline"], "2026-10-07")
        self.assertEqual(jobs[0]["apply_url"], "https://example.com/apply")
        self.assertEqual(jobs[0]["notice_url"], "https://mp.weixin.qq.com/s/example")

    def test_dedupe_jobs_keeps_first_company_apply_url_pair(self):
        first = {"company": "A", "apply_url": "https://example.com/a", "page": 1}
        duplicate = {"company": "A", "apply_url": "https://example.com/a", "page": 2}
        other = {"company": "A", "apply_url": "https://example.com/b", "page": 2}

        self.assertEqual(dedupe_jobs([first, duplicate, other]), [first, other])

    def test_extract_jobs_keeps_non_url_apply_instructions(self):
        html = """
        <tr data-id="1">
          <td class="crt-col-company">邮箱投递公司</td>
          <td class="crt-col-links">
            <a href="邮箱投递：resume@example.com（邮件主题：学校+姓名）" class="crt-link">投递</a>
          </td>
        </tr>
        """

        jobs = extract_jobs(html, page=1)

        self.assertEqual(jobs[0]["apply_url"], "邮箱投递：resume@example.com（邮件主题：学校+姓名）")


if __name__ == "__main__":
    unittest.main()
