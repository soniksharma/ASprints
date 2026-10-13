import unittest

from accesssprint.url_policy import UrlPolicyError, is_public_address, normalize_page_url


class NormalizePageUrlTests(unittest.TestCase):
    def test_accepts_and_trims_http_url(self):
        self.assertEqual(normalize_page_url("  http://example.com/path?q=1  "),
                         "http://example.com/path?q=1")

    def test_accepts_https_url(self):
        self.assertEqual(normalize_page_url("https://example.com"), "https://example.com/")

    def test_rejects_unsupported_scheme(self):
        with self.assertRaises(UrlPolicyError):
            normalize_page_url("file:///etc/passwd")

    def test_rejects_malformed_host(self):
        with self.assertRaises(UrlPolicyError):
            normalize_page_url("https://not a host/path")

    def test_rejects_url_credentials(self):
        with self.assertRaises(UrlPolicyError):
            normalize_page_url("https://auditor:secret@example.com/")

    def test_rejects_localhost_names(self):
        for host in ("localhost", "sub.localhost", "printer.local"):
            with self.subTest(host=host), self.assertRaises(UrlPolicyError):
                normalize_page_url(f"http://{host}/")

    def test_rejects_private_and_link_local_ipv4(self):
        for address in ("127.0.0.1", "10.2.3.4", "172.16.0.1", "192.168.1.3", "169.254.2.5"):
            with self.subTest(address=address), self.assertRaises(UrlPolicyError):
                normalize_page_url(f"http://{address}/")

    def test_rejects_loopback_and_unique_local_ipv6(self):
        for address in ("[::1]", "[fc00::1]", "[fe80::1]"):
            with self.subTest(address=address), self.assertRaises(UrlPolicyError):
                normalize_page_url(f"http://{address}/")

    def test_rejects_missing_hostname(self):
        with self.assertRaises(UrlPolicyError):
            normalize_page_url("https:///path")


class PublicAddressTests(unittest.TestCase):
    def test_accepts_public_ipv4_and_ipv6(self):
        self.assertTrue(is_public_address("8.8.8.8"))
        self.assertTrue(is_public_address("2606:4700:4700::1111"))

    def test_rejects_non_public_address_ranges(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.1.1", "192.168.1.1",
                        "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1", "ff02::1"):
            with self.subTest(address=address):
                self.assertFalse(is_public_address(address))

    def test_rejects_non_ip_input(self):
        self.assertFalse(is_public_address("example.com"))


if __name__ == "__main__":
    unittest.main()
