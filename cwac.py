"""Centralised Web Accessibility Checker.

This is the main entry point script for CWAC.
Refer to the README for more information.
"""

import concurrent.futures
import csv
import logging
import os
import random
from queue import SimpleQueue
from typing import Any
from urllib.parse import urlparse, urlunparse

import src.verify
from config import config
from src.analytics import Analytics
from src.browser import Browser
from src.crawler import Crawler
from src.output import output_init_message


class CWAC:
    """Main CWAC class."""

    # Global queue of URLs to scan
    url_queue: SimpleQueue[dict[Any, Any]]

    # Global anaytics for the scan
    analytics = Analytics()

    def thread(self, thread_id: int) -> None:
        """Start a browser, and start crawling.

        Args:
            thread_id (int): identifier for the thread
        """
        browser = Browser(thread_id)
        crawl = Crawler(browser=browser, url_queue=CWAC.url_queue, analytics=CWAC.analytics)
        crawl.iterate_through_base_urls()
        browser.close()

    def spawn_threads(self) -> None:
        """Create a number of threads to speed up execution.

        Number of threads defined by config.json.thread_count.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.thread_count) as executor:
            results = {executor.submit(self.thread, thread_id): thread_id for thread_id in range(config.thread_count)}
        for result in results:
            result.result()
        logging.info("All threads complete")

    def should_skip_row(self, row: dict[Any, Any]) -> bool:
        """Check if a row being imported should be skipped.

        Checks if a URL/Organisation should be included
        in the audit according to config_default.json's
        filter_to_organisations and
        filter_to_domains.

        Args:
            row (dict[Any, Any]): a row from a CSV

        Returns:
            bool: True if the row should be skipped, False otherwise
        """
        found_org = False
        if config.filter_to_organisations:
            for org in config.filter_to_organisations:
                if org in row["organisation"]:
                    found_org = True
                    break

        found_domain = False
        if config.filter_to_domains:
            for domain in config.filter_to_domains:
                if domain in row["url"]:
                    found_domain = True
                    break

        if config.filter_to_organisations and config.filter_to_domains:
            return not (found_org and found_domain)
        if config.filter_to_organisations:
            return not found_org
        if config.filter_to_domains:
            return not found_domain

        return False

    def lowercase_url(self, url: str) -> str:
        """Make URL protocl/netloc lowercase.

        Args:
            url (str): URL to make lowercase

        Returns:
            str: lowercase URL
        """
        parsed = urlparse(url)
        modified = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower())
        return urlunparse(modified)

    def shuffle_queue(self, queue: SimpleQueue[Any]) -> None:
        """Shuffle a SimpleQueue.

        Args:
            queue (SimpleQueue[dict[Any, Any]]): the queue to shuffle
        """
        # Convert queue to list
        queue_list = []
        while not queue.empty():
            queue_list.append(queue.get())

        # Shuffle the list
        random.shuffle(queue_list)

        # Iterate through the list and add back to queue
        for item in queue_list:
            queue.put(item)

    def import_base_urls(self) -> SimpleQueue[dict[Any, Any]]:
        """Import target URLs for crawl mode.

        This function reads all CSVs in config.base_urls_crawl_path
        and returns a SimpleQueue of each row

        Returns:
            SimpleQueue: a SimpleQueue of URLs
        """
        folder_path = config.base_urls_crawl_path

        if config.nocrawl_mode:
            folder_path = config.base_urls_nocrawl_path
            config.max_links_per_domain = 1

        url_queue: SimpleQueue[dict[Any, Any]] = SimpleQueue()

        for filename in os.listdir(folder_path):
            if filename.endswith(".csv"):
                with open(
                    os.path.join(folder_path, filename),
                    encoding="utf-8",
                    newline="",
                ) as file:
                    reader = csv.reader(file)
                    header = next(reader)
                    for row in reader:
                        dict_row = dict(zip(header, row))
                        if self.should_skip_row(dict_row):
                            continue

                        # Strip whitespace from URL
                        dict_row["url"] = dict_row["url"].strip()

                        # Make the URL lowercase
                        dict_row["url"] = self.lowercase_url(dict_row["url"])

                        CWAC.analytics.init_pages_scanned(dict_row["url"])

                        # Add the base_url to analytics.base_urls
                        CWAC.analytics.base_urls.add(dict_row["url"])

                        url_queue.put(dict_row)

        # If shuffle_queue is True, shuffle the queue
        if config.shuffle_base_urls:
            self.shuffle_queue(url_queue)
        return url_queue

    def __init__(self) -> None:
        """Set up CWAC and run the test.

        Imports target URLs, sets up Analytics, creates
        relevant folders, spawns a number of threads, then
        finally verifies the results of the test.
        """
        # Print the initial message
        output_init_message()

        # Import base_urls into global varaiable
        CWAC.url_queue = self.import_base_urls()

        # Print the number of URLs to be scanned
        num_websites_msg = f"Number of websites to be scanned: {CWAC.url_queue.qsize()}"
        print(num_websites_msg)
        print("*" * 80)
        logging.info(num_websites_msg)

        # Set the estimated number of pages in the analytics object
        self.analytics.est_num_pages_in_test = CWAC.url_queue.qsize() * config.max_links_per_domain

        if config.thread_count == 1:
            # Run CWAC without threading (useful for profiling)
            self.thread(0)
        else:
            # Run CWAC with multithreading
            self.spawn_threads()

        # Verify results
        src.verify.verify_axe_results(pages_scanned=self.analytics.pages_scanned)

        print("\r\n")
        print("-" * 80)
        print("\r\nCWAC complete! Data can be found", "in the ./results folder.")

        logging.info("CWAC complete!")


if __name__ == "__main__":
    cwac: CWAC = CWAC()
