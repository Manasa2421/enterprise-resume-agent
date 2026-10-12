"""
Static domain knowledge used by the agents.

Keeping this data separate from agent logic means it can later be moved to a
database or config service without touching agent code.
"""

# Keywords that ATS systems commonly screen for, grouped by career domain.
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "Data Analytics": [
        "SQL", "Python", "Power BI", "Tableau", "Excel", "Data Visualization",
        "ETL", "Statistics", "Dashboarding", "Data Modeling", "KPI Reporting",
        "Pandas", "A/B Testing", "Data Cleaning", "Stakeholder Management",
    ],
    "Data Science & Machine Learning": [
        "Python", "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
        "Scikit-learn", "NLP", "Statistics", "Feature Engineering",
        "Model Deployment", "MLOps", "SQL", "Pandas", "Computer Vision", "LLM",
    ],
    "Software Engineering": [
        "Java", "Python", "JavaScript", "TypeScript", "REST APIs", "Microservices",
        "Git", "CI/CD", "Docker", "Unit Testing", "System Design", "Agile",
        "SQL", "Cloud", "Kubernetes",
    ],
    "Frontend Development": [
        "JavaScript", "TypeScript", "React", "HTML", "CSS", "Redux", "Next.js",
        "Responsive Design", "Accessibility", "Jest", "Webpack", "REST APIs",
        "Git", "UI/UX", "Performance Optimization",
    ],
    "DevOps & Cloud": [
        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD",
        "Jenkins", "Linux", "Monitoring", "Ansible", "Infrastructure as Code",
        "Python", "Bash", "Prometheus",
    ],
    "Cybersecurity": [
        "SIEM", "Incident Response", "Vulnerability Management", "Network Security",
        "Penetration Testing", "ISO 27001", "NIST", "Firewalls", "IAM",
        "Threat Intelligence", "Splunk", "Risk Assessment", "Python",
        "Cloud Security", "SOC",
    ],
    "Project Management": [
        "Agile", "Scrum", "Jira", "Stakeholder Management", "Risk Management",
        "Budgeting", "PMP", "Roadmapping", "Resource Planning", "Waterfall",
        "Kanban", "Cross-functional Leadership", "Reporting", "Confluence",
        "Change Management",
    ],
    "Digital Marketing": [
        "SEO", "SEM", "Google Analytics", "Content Strategy", "Social Media",
        "Email Marketing", "Google Ads", "Campaign Management", "HubSpot",
        "Conversion Optimization", "Copywriting", "A/B Testing", "CRM",
        "Marketing Automation", "Brand Strategy",
    ],
}

# Words in job titles / target role that signal a domain (lower-case).
DOMAIN_TITLE_SIGNALS: dict[str, list[str]] = {
    "Data Analytics": ["data analyst", "analytics", "business intelligence", "bi analyst", "reporting analyst", "business analyst"],
    "Data Science & Machine Learning": ["data scientist", "machine learning", "ml engineer", "ai engineer", "research scientist"],
    "Software Engineering": ["software engineer", "software developer", "backend", "full stack", "full-stack", "programmer", "sde"],
    "Frontend Development": ["frontend", "front-end", "ui developer", "web developer", "react developer"],
    "DevOps & Cloud": ["devops", "cloud engineer", "site reliability", "sre", "platform engineer", "infrastructure"],
    "Cybersecurity": ["security", "soc analyst", "penetration", "cyber", "infosec"],
    "Project Management": ["project manager", "program manager", "scrum master", "delivery manager", "product owner"],
    "Digital Marketing": ["marketing", "seo", "growth", "content strategist", "brand"],
}

# Categories used to group the skills section of the resume.
SKILL_CATEGORIES: dict[str, list[str]] = {
    "Programming Languages": [
        "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust",
        "R", "Scala", "Kotlin", "Swift", "PHP", "Ruby", "Bash", "SQL",
    ],
    "Data & Analytics": [
        "Power BI", "Tableau", "Excel", "Looker", "Pandas", "NumPy", "Statistics",
        "Data Visualization", "ETL", "Data Modeling", "Data Cleaning",
        "A/B Testing", "KPI Reporting", "Dashboarding", "Google Analytics",
    ],
    "AI & Machine Learning": [
        "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
        "Scikit-learn", "NLP", "Computer Vision", "LLM", "Feature Engineering",
        "MLOps", "Model Deployment",
    ],
    "Cloud & DevOps": [
        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD",
        "Jenkins", "Linux", "Ansible", "Prometheus", "Infrastructure as Code",
        "Monitoring", "Cloud",
    ],
    "Frameworks & Libraries": [
        "React", "Next.js", "Redux", "Angular", "Vue", "Django", "Flask",
        "FastAPI", "Spring Boot", "Node.js", "Express", "Jest", "Webpack",
    ],
    "Databases": [
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Snowflake", "BigQuery",
        "Oracle", "SQL Server", "Cassandra", "DynamoDB",
    ],
    "Tools & Platforms": [
        "Git", "Jira", "Confluence", "Splunk", "HubSpot", "Salesforce",
        "Figma", "SAP", "Airflow", "dbt", "Databricks",
    ],
    "Methodologies": [
        "Agile", "Scrum", "Kanban", "Waterfall", "DevOps", "TDD", "Unit Testing",
        "System Design", "Microservices", "REST APIs", "Stakeholder Management",
        "Risk Management", "Change Management",
    ],
}

# Alternate spellings → canonical skill name (keys are lower-case).
SKILL_ALIASES: dict[str, str] = {
    "powerbi": "Power BI",
    "power-bi": "Power BI",
    "ms excel": "Excel",
    "microsoft excel": "Excel",
    "k8s": "Kubernetes",
    "js": "JavaScript",
    "ts": "TypeScript",
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "postgres": "PostgreSQL",
    "sklearn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "google cloud": "GCP",
    "amazon web services": "AWS",
    "rest api": "REST APIs",
    "restful apis": "REST APIs",
    "reactjs": "React",
    "react.js": "React",
    "nodejs": "Node.js",
    "ci cd": "CI/CD",
    "natural language processing": "NLP",
}

# Strong action verbs that recruiters and ATS parsers favour (lower-case).
ACTION_VERBS: set[str] = {
    "accelerated", "achieved", "analyzed", "architected", "automated", "boosted",
    "built", "championed", "collaborated", "configured", "consolidated",
    "contributed", "coordinated", "created", "cut", "decreased", "defined",
    "delivered", "deployed", "designed", "developed", "directed", "drove",
    "enabled", "engineered", "established", "evaluated", "executed", "expanded",
    "facilitated", "forecasted", "generated", "grew", "guided", "handled",
    "identified", "implemented", "improved", "increased", "integrated",
    "introduced", "launched", "led", "maintained", "managed", "mentored",
    "migrated", "modeled", "modernized", "monitored", "negotiated", "optimized",
    "orchestrated", "organized", "oversaw", "partnered", "performed", "pioneered",
    "planned", "presented", "prioritized", "produced", "reduced", "redesigned",
    "refactored", "resolved", "restructured", "saved", "scaled", "secured",
    "simplified", "spearheaded", "standardized", "streamlined", "strengthened",
    "supported", "tested", "trained", "transformed", "translated", "upgraded",
    "validated", "visualized", "wrote",
}

# Weak openers → stronger replacements (keys are lower-case, matched at start).
WEAK_PHRASES: dict[str, str] = {
    "responsible for": "Managed",
    "was responsible for": "Managed",
    "worked on": "Contributed to",
    "was involved in": "Contributed to",
    "involved in": "Contributed to",
    "helped with": "Supported",
    "helped to": "Helped",
    "duties included": "Handled",
    "tasked with": "Executed",
    "in charge of": "Led",
}

# Common misspellings found in resumes → correction (lower-case).
COMMON_MISSPELLINGS: dict[str, str] = {
    "managment": "management",
    "acheived": "achieved",
    "acheivement": "achievement",
    "responsibilty": "responsibility",
    "developement": "development",
    "recieved": "received",
    "seperate": "separate",
    "occured": "occurred",
    "succesful": "successful",
    "successfull": "successful",
    "analyse": "analyze",
    "teh": "the",
    "enviroment": "environment",
    "comunication": "communication",
    "buisness": "business",
}

FIRST_PERSON_PRONOUNS = ("i", "me", "my", "mine", "we", "our", "us")
