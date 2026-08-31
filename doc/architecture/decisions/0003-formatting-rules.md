# 2. Formatting Rules

**Date**: 2025-11-10

**Updated**: 2026-03-17

**Previous ID**: ADR-0002

## Status

Accepted

## Context

The Swedish Pathogens Portal codebase needs consistent formatting rules to ensure code readability, maintainability, and ease of code reviews. Currently, some formatting rules are documented (Python via Ruff configuration), while others are implicit or undocumented (HTML templates, file naming, URLs, docstrings).

Formalizing these rules will:
- Improve code consistency across the project
- Make code reviews more efficient
- Reduce formatting debates during development
- Provide clear guidelines for new team members
- Ensure better developer experience

## Decision

We will adopt the following formatting rules for the Swedish Pathogens Portal project:

### HTML Formatting
- **Line Length**: Aim for approximately 100-120 characters per line in HTML template files, primarily referring to content/text displayed on webpages (e.g., text within `<p>`, `<h1>`, `<div>`, and other content tags). This is a guideline rather than a hard threshold, as there is no good automated tool to enforce it for HTML and also there could be exceptions like really long urls.
- **Indentation**: If indentation is used, it should be 4 spaces (consistent with Python formatting).
- **Rationale**: Improves readability in code reviews, easier to view in terminal/IDE side-by-side, aligns with common HTML style guides. Prevents overly long lines that are hard to scan, especially for content that will be displayed to users. The guideline is more lenient than Python's 100-character limit to account for HTML's structure and TailwindCSS utility classes.
- **Note**: While HTML templates with TailwindCSS utility classes can create long lines in code, the line length guideline primarily applies to visible content/text. Code formatting (attributes, class lists) may exceed this guideline when necessary for readability. Since there's no good automated tool to enforce HTML line length, this is a soft guideline to avoid overly long lines when possible.
- **Enforcement**: Manual code review. Automated tooling (e.g., Prettier, HTML linters) may be considered in the future, but currently there is no reliable tool to enforce HTML line length.

### File Naming Convention
- **Rule**: Use lowercase with underscores for all file names (e.g., `my_file_name.html`, `topic_detail.py`)
- **Rationale**: 
  - Consistent with Python conventions (PEP 8)
  - Consistent with Django best practices
  - Avoids case-sensitivity issues across operating systems
- **Examples**:
  - ✅ `models.py`, `topic_detail.html`, `article_detail.html`
  - ❌ `Models.py`, `TopicDetail.html`, `article-detail.html`
- **Current State**: Already followed throughout the codebase

### URL Naming Convention
- **Rule**: Use lowercase with dashes (hyphens) in URL paths (e.g., `/my-website-url/`, `/topic-detail/`)
- **Rationale**: 
  - More readable than underscores in URLs
  - SEO-friendly (search engines prefer dashes and lowercase)
  - Consistent with web standards and best practices
  - Avoids case-sensitivity issues
  - Django's `SlugField` automatically converts to lowercase and dashes
- **Examples**:
  - ✅ `/topics/covid-19-research/`, `/articles/my-article-title/`
  - ❌ `/topics/covid_19_research/`, `/articles/MyArticleTitle/`, `/topics/COVID-19-Research/`
- **Current State**: Already implemented via Django slug fields throughout the codebase

### Docstring Format
- **Rule**: Use Google-style docstrings for complex classes, models, and functions. Use single-line docstrings only for very simple functions and methods (e.g., `__str__`, simple property getters, straightforward save methods)
- **Format**: 
  - **Single-line**: `"""Brief description of the function/class."""`
  - **Google-style**: Multi-line docstrings with Attributes, Examples, and detailed descriptions for complex code
- **Rationale**: 
  - Google-style docstrings provide comprehensive documentation for complex code, improving maintainability
  - Single-line docstrings are sufficient for very simple functions where additional documentation adds no value
- **Examples**:
  ```python
  # Good: Single-line for very simple methods
  def __str__(self):
      """Return the topic name for string representation."""
      return self.name


  # Good: Single-line for simple properties
  @property
  def display_image(self):
      """Return the URL of the thumbnail image."""
      return self.thumbnail_image.url


  # Good: Google-style for complex models/classes
  class Article(models.Model):
      """Article model for showcasing research findings and editorial content.

      Represents articles (data highlights and editorials) that showcase important
      scientific findings, data insights, and editorial content for the Swedish
      Pathogens Portal.

      Attributes:
          type (str): Content type - either "Editorial" or "Data Highlight".
          title (str): Display title of the article (max 255 chars, unique).
          slug (str): URL-friendly version of title (auto-generated).
          # ... more attributes
      """

      # Implementation
  ```

### Python Formatting Rules
These rules are enforced via Ruff configuration in `pyproject.toml`:

- **Line Length**: 88 characters (Ruff configuration)
- **Indentation**: 4 spaces (Ruff configuration)
- **String Quotes**: Double quotes for all strings (Ruff configuration)
- **Type Hints**: Required (Ruff ANN rules)
- **Import Sorting**: Automatic via isort (Ruff I rules)
- **Code Style**: PEP 8 compliant via Ruff

## Consequences

### Positive
- **Consistent codebase appearance**: All code follows the same formatting standards
- **Easier code reviews**: Reviewers can focus on logic rather than formatting
- **Better developer experience**: Clear guidelines reduce confusion and debates
- **Reduced formatting discussions**: Decisions are documented and agreed upon
- **Improved maintainability**: Consistent formatting makes code easier to understand and modify

### Negative
- **Enforcement overhead**: Rules need to be checked and verified during code reviews, adding to review time
- **Manual enforcement**: HTML line length and docstring format require manual verification as automated tooling is not currently configured
- **Consistency maintenance**: Team members must remember and apply rules consistently across all code changes
- **HTML content formatting**: May require more line breaks in content text within HTML tags to follow the line length guideline

### Mitigation
- Code review checklists can include formatting rule verification to ensure consistency
- ADR documentation provides clear reference for all formatting rules
- Examples in this ADR demonstrate correct usage patterns
- HTML line length is a soft guideline (90-100 characters) - exceptions are acceptable when breaking would harm readability or when dealing with code formatting (attributes, class lists)
