from datetime import datetime

import pytz
import requests
from lxml import etree, html


class MessageParser:
    def __init__(self, html_content, current_user="jojiku"):
        self.html_content = html_content
        self.current_user = current_user
        self.current_time = datetime(2025, 1, 1, 13, 32, 19, tzinfo=pytz.UTC)
        self.xpath = "/html/body/div[1]/div[1]/div/div[0]/div/table/tbody/tr/td/msg/hyp[1]/text()"

    def parse_message(self):
        try:
            # Parse the HTML content
            tree = html.fromstring(self.html_content)

            # Try to find the element using xpath
            message = tree.xpath(self.xpath)

            # Print datetime and user information
            print(
                f"Current Date and Time (UTC): {self.current_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            print(f"Current User's Login: {self.current_user}")

            # Return the message if found
            if message:
                return message[0]
            else:
                return "No message found at specified XPath"

        except etree.XMLSyntaxError as e:
            return f"XML parsing error: {str(e)}"
        except etree.XPathEvalError as e:
            return f"XPath evaluation error: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"


def load_and_parse_html(url_or_file):
    try:
        # Check if input is a URL or file content
        if url_or_file.startswith(("http://", "https://")):
            response = requests.get(url_or_file)
            html_content = response.text
        else:
            html_content = url_or_file
        print(html_content)
        # Create parser instance and parse message
        parser = MessageParser(html_content)
        result = parser.parse_message()

        return result

    except requests.RequestException as e:
        return f"Failed to fetch URL: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


def main():
    url = "http://127.0.0.1:49135/wg/c/?m=main&l=0&i=0&t=0&n=dark&r=0&h=1&bg=0&co=%23FFFFFF#g76561198381732074-t1baloo9"
    result = load_and_parse_html(url)

    print("\nParsed Message:")
    print(result)


if __name__ == "__main__":
    main()
