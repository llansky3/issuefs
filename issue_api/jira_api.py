import requests

from .issue import IssueInfo, IssueComment


class IssueInfo_Jira(IssueInfo):
    """JIRA-specific issue information."""
    
    def __init__(self, key, summary, description, jira_url=None):
        super().__init__(key, summary, description)
        self.jira_url = jira_url
    
    def to_html(self):
        if self.jira_url:
            return f'<a href="{self.jira_url}/browse/{self.key}">{self.key}</a>: {self.summary}'
        return f'{self.key}: {self.summary}'

    def to_ai(self):
        return super().to_ai(tracker_type="Jira")


class Jira:
    def __init__(self, url, token):
        self.url = url
        self.token = token

    def headers(self):
        return {
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/json'
        }

    def search(self, query, fields=['key','summary','description','comments']):
        # Comments are treated in a special way
        if 'comments' in fields:
            include_comments = True
            fields.remove('comments')
        else:
            include_comments = False

        fields_to_get = ",".join(fields)    
        url_to_get = f'{self.url}/rest/api/2/search?jql={query}&fields={fields_to_get}'           
        result = requests.get(url_to_get, 
            headers=self.headers()
            ).json()

        issues = []
        for issue in result['issues']:
            i = IssueInfo_Jira(
                issue['key'],
                issue['fields']['summary'],
                issue['fields']['description'],
                jira_url=self.url
            )
            if include_comments:
                i.comments = self.get_comments(issue['key'])
            issues.append(i)
        return issues

    def get_comments(self, issue):
        api_endpoint = f"{self.url}/rest/api/2/issue/{issue}/comment"
        result = requests.get(api_endpoint, headers=self.headers()).json()
        comments = []
        for comment in result.get("comments", []):
            comments.append(IssueComment(
                comment['author']['displayName'],
                comment['body'],
                comment['created']
            ))
        return comments

    def get_issue(self, issue_key, include_comments=True):
        """
        Get a single issue by its key.
        
        Args:
            issue_key: JIRA issue key (e.g., 'ABC-1234')
            include_comments: Whether to include comments (default: True)
        
        Returns:
            IssueInfo_Jira object or None if issue not found
        """
        try:
            url_to_get = f'{self.url}/rest/api/2/issue/{issue_key}?fields=key,summary,description'
            result = requests.get(url_to_get, headers=self.headers(), timeout=10)
            result.raise_for_status()
            data = result.json()
            
            i = IssueInfo_Jira(
                data['key'],
                data['fields']['summary'],
                data['fields'].get('description', ''),
                jira_url=self.url
            )
            if include_comments:
                i.comments = self.get_comments(data['key'])
            return i
        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not fetch JIRA issue {issue_key}: {e}")
            return None

    def api(self, issue, fields=['summary']):
        fields_to_get = ",".join(fields)
        url_to_get = f'{self.url}/rest/api/2/issue/{issue}?fields={fields_to_get}'
        result = requests.get(url_to_get, headers=self.headers()).json()
        out = {}
        for f in fields:
            out[f] = result['fields'][f]
        return out

    def version(self):
        """
        Test connection to JIRA API and return server information.
        Returns a dict with version info if successful, None if connection fails.
        """
        try:
            url_to_get = f'{self.url}/rest/api/2/serverInfo'
            result = requests.get(url_to_get, headers=self.headers(), timeout=10)
            result.raise_for_status()
            data = result.json()
            return {
                'success': True,
                'version': data.get('version', 'unknown'),
                'build': data.get('buildNumber', 'unknown'),
                'server_title': data.get('serverTitle', 'JIRA'),
                'base_url': data.get('baseUrl', self.url)
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }