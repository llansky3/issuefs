"""
Base class for issue tracker API clients.

This module provides a common interface for different issue tracking systems
(JIRA, GitHub, Bugzilla) to reduce code duplication and maintain consistency.
"""

from abc import ABC, abstractmethod


class IssueTrackerClient(ABC):
    """
    Abstract base class for issue tracker API clients.
    
    All issue tracker implementations (JIRA, GitHub, Bugzilla) should inherit
    from this class and implement the required abstract methods.
    """
    
    def __init__(self, url, token):
        """
        Initialize the issue tracker client.
        
        Args:
            url: Base URL of the issue tracker API
            token: Authentication token for API access
        """
        self.url = url
        self.token = token
    
    @abstractmethod
    def headers(self):
        """
        Return HTTP headers required for API requests.
        
        Returns:
            Dictionary of HTTP headers
        """
        pass
    
    @abstractmethod
    def search(self, query, **kwargs):
        """
        Search for issues matching the given query.
        
        Args:
            query: Search query (format depends on the tracker type)
            **kwargs: Additional parameters specific to the tracker
        
        Returns:
            List of IssueInfo objects
        """
        pass
    
    @abstractmethod
    def get_comments(self, issue_id, **kwargs):
        """
        Get comments for a specific issue.
        
        Args:
            issue_id: Issue identifier (key, number, or ID depending on tracker)
            **kwargs: Additional parameters specific to the tracker
        
        Returns:
            List of IssueComment objects
        """
        pass
    
    @abstractmethod
    def get_issue(self, issue_id, include_comments=True, **kwargs):
        """
        Get a single issue by its identifier.
        
        Args:
            issue_id: Issue identifier (key, number, or ID depending on tracker)
            include_comments: Whether to include comments (default: True)
            **kwargs: Additional parameters specific to the tracker
        
        Returns:
            IssueInfo object or None if issue not found
        """
        pass
    
    @abstractmethod
    def version(self):
        """
        Test connection to the API and return server information.
        
        Returns:
            Dictionary with version info:
            - success: bool indicating if connection was successful
            - version: version string
            - error: error message (if success is False)
            Additional fields may vary by tracker type
        """
        pass
    
    def get_tracker_name(self):
        """
        Return the name of this tracker type.
        
        Returns:
            String name of the tracker (e.g., "JIRA", "GitHub", "Bugzilla")
        """
        return self.__class__.__name__
