from dataclasses import dataclass

class IssueInfo:
    """Base class for issue information from various tracking systems.""" 
    def __init__(self, key, summary, description):
        self.key = key
        self.summary = summary
        self.description = description
        self.comments = []
    
    def __str__(self):
        return f'Issue {self.key}: {self.summary}'

    def to_html(self):
        """Return HTML representation. Should be overridden by subclasses."""
        return f'{self.key}: {self.summary}'

    def to_ai(self, tracker_type=None):
        """Return AI-friendly text representation."""
        r = f'{tracker_type} issue: {self.key}' if tracker_type else f'Issue: {self.key}'
        r += f'\nSummary: {self.summary}'
        r += f'\nDescription: {self.description}'
        for c in self.comments:
            r += f'\n{c.__str__()}'
        r += f'\nEnd of {tracker_type} issue {self.key} information'
        return r

    @property
    def id(self):
        return self.key


@dataclass
class IssueComment:
    author:     str
    text:       str
    created:    str
    
    def __str__(self):
        return f'Comment by {self.author} on {self.created}: {self.text}'

    def to_html(self):
        return self.__str__()