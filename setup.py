from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="vspagent",
    version="3.2.0",
    author="Vishnu Suresh Perumbavoor",
    description="Universal Google Colab MCP & JarvisLabs Cloud GPU Agent Harness.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/vishnusureshperumbavoor/vspagent",
    project_urls={
        "Bug Tracker": "https://github.com/vishnusureshperumbavoor/vspagent/issues",
        "LinkedIn": "https://www.linkedin.com/in/vishnu-suresh-perumbavoor/",
        "GitHub": "https://github.com/vishnusureshperumbavoor",
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "pydantic>=1.10.0",
        "rich>=12.0.0",
    ],
    entry_points={
        "console_scripts": [
            "vspagent=vspagent.cli:main",
        ],
    },
    keywords="colab mcp model-context-protocol gpu fine-tuning cloud-execution ai-agent",
)
