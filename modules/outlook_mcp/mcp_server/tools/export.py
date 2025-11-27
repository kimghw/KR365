"""Export tools for MCP server"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from infra.utils.datetime_utils import to_local_filename, format_for_display, utc_now

logger = logging.getLogger(__name__)


class ExportTool:
    """Tool for exporting email data to various formats"""

    def __init__(self, config):
        """
        Initialize export tool

        Args:
            config: Configuration object
        """
        self.config = config
        self.exports_dir = Path(self.config.exports_dir)

    def save_emails_to_csv(self, emails: List[Dict[str, Any]], user_id: str) -> Path:
        """
        Save email data to CSV file

        Args:
            emails: List of email dictionaries
            user_id: User ID

        Returns:
            Path to saved CSV file
        """
        # Create output directory
        csv_dir = self.exports_dir / user_id
        csv_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp (UTC)
        timestamp = to_local_filename()
        csv_file = csv_dir / f"email_metadata_{timestamp}.csv"

        # Write CSV
        with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            if emails:
                # Define field names
                fieldnames = [
                    'subject', 'sender', 'sender_email', 'received_date',
                    'has_attachments', 'is_read', 'importance', 'body_preview'
                ]

                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for email in emails:
                    row = {
                        'subject': email.get('subject', ''),
                        'sender': email.get('sender', ''),
                        'sender_email': email.get('sender_email', ''),
                        'received_date': email.get('received_date', ''),
                        'has_attachments': email.get('has_attachments', False),
                        'is_read': email.get('is_read', False),
                        'importance': email.get('importance', 'normal'),
                        'body_preview': self._truncate_text(
                            email.get('body', '') or email.get('body_preview', ''),
                            200
                        )
                    }
                    writer.writerow(row)

        logger.info(f"CSV file saved: {csv_file}")
        return csv_file

    def save_emails_to_json(self, emails: List[Dict[str, Any]], user_id: str) -> Path:
        """
        Save email data to JSON file

        Args:
            emails: List of email dictionaries
            user_id: User ID

        Returns:
            Path to saved JSON file
        """
        # Create output directory
        json_dir = self.exports_dir / user_id
        json_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp (UTC)
        timestamp = to_local_filename()
        json_file = json_dir / f"email_metadata_{timestamp}.json"

        # Write JSON
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(emails, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"JSON file saved: {json_file}")
        return json_file

    def export_email_summary(self, emails: List[Dict[str, Any]], user_id: str,
                            format: str = "markdown") -> Path:
        """
        Export email summary in specified format

        Args:
            emails: List of email dictionaries
            user_id: User ID
            format: Export format (markdown, html, txt)

        Returns:
            Path to saved summary file
        """
        # Create output directory
        summary_dir = self.exports_dir / user_id / "summaries"
        summary_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp (UTC)
        timestamp = to_local_filename()

        if format == "markdown":
            return self._export_markdown_summary(emails, summary_dir, timestamp)
        elif format == "html":
            return self._export_html_summary(emails, summary_dir, timestamp)
        else:
            return self._export_text_summary(emails, summary_dir, timestamp)

    def _export_markdown_summary(self, emails: List[Dict[str, Any]],
                                 output_dir: Path, timestamp: str) -> Path:
        """Export summary as markdown"""
        md_file = output_dir / f"email_summary_{timestamp}.md"

        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(f"# Email Summary\n\n")
            f.write(f"Generated: {format_for_display(utc_now())}\n\n")
            f.write(f"Total emails: {len(emails)}\n\n")

            f.write("## Email List\n\n")

            for i, email in enumerate(emails, 1):
                f.write(f"### {i}. {email.get('subject', 'No Subject')}\n\n")
                f.write(f"- **From:** {email.get('sender', 'Unknown')}\n")
                f.write(f"- **Date:** {email.get('received_date', 'Unknown')}\n")
                f.write(f"- **Attachments:** {email.get('has_attachments', False)}\n")
                f.write(f"- **Read:** {email.get('is_read', False)}\n")

                if email.get('body'):
                    f.write(f"\n**Preview:**\n\n")
                    f.write(f"> {self._truncate_text(email['body'], 300)}\n")

                f.write("\n---\n\n")

        logger.info(f"Markdown summary saved: {md_file}")
        return md_file

    def _export_html_summary(self, emails: List[Dict[str, Any]],
                            output_dir: Path, timestamp: str) -> Path:
        """Export summary as HTML"""
        html_file = output_dir / f"email_summary_{timestamp}.html"

        with open(html_file, 'w', encoding='utf-8') as f:
            f.write("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Email Summary</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { color: #333; }
        .email { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }
        .email h3 { margin-top: 0; color: #0066cc; }
        .meta { color: #666; font-size: 0.9em; }
        .preview { background: #f5f5f5; padding: 10px; margin-top: 10px; border-left: 3px solid #0066cc; }
    </style>
</head>
<body>
""")
            f.write(f"<h1>Email Summary</h1>\n")
            f.write(f"<p>Generated: {format_for_display(utc_now())}</p>\n")
            f.write(f"<p>Total emails: {len(emails)}</p>\n\n")

            for i, email in enumerate(emails, 1):
                f.write('<div class="email">\n')
                f.write(f"<h3>{i}. {self._escape_html(email.get('subject', 'No Subject'))}</h3>\n")
                f.write('<div class="meta">\n')
                f.write(f"<strong>From:</strong> {self._escape_html(email.get('sender', 'Unknown'))}<br>\n")
                f.write(f"<strong>Date:</strong> {email.get('received_date', 'Unknown')}<br>\n")
                f.write(f"<strong>Attachments:</strong> {email.get('has_attachments', False)}<br>\n")
                f.write(f"<strong>Read:</strong> {email.get('is_read', False)}\n")
                f.write('</div>\n')

                if email.get('body'):
                    f.write('<div class="preview">\n')
                    f.write(f"{self._escape_html(self._truncate_text(email['body'], 300))}\n")
                    f.write('</div>\n')

                f.write('</div>\n')

            f.write("</body>\n</html>")

        logger.info(f"HTML summary saved: {html_file}")
        return html_file

    def _export_text_summary(self, emails: List[Dict[str, Any]],
                            output_dir: Path, timestamp: str) -> Path:
        """Export summary as plain text"""
        txt_file = output_dir / f"email_summary_{timestamp}.txt"

        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write("EMAIL SUMMARY\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Generated: {format_for_display(utc_now())}\n")
            f.write(f"Total emails: {len(emails)}\n\n")

            for i, email in enumerate(emails, 1):
                f.write(f"{i}. {email.get('subject', 'No Subject')}\n")
                f.write("-" * 40 + "\n")
                f.write(f"From: {email.get('sender', 'Unknown')}\n")
                f.write(f"Date: {email.get('received_date', 'Unknown')}\n")
                f.write(f"Attachments: {email.get('has_attachments', False)}\n")
                f.write(f"Read: {email.get('is_read', False)}\n")

                if email.get('body'):
                    f.write("\nPreview:\n")
                    f.write(f"{self._truncate_text(email['body'], 300)}\n")

                f.write("\n" + "=" * 60 + "\n\n")

        logger.info(f"Text summary saved: {txt_file}")
        return txt_file

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text to specified length"""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters"""
        if not text:
            return ""
        return (text.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace('"', "&quot;")
                   .replace("'", "&#39;"))