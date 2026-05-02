from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="vspagent",
    version="2.2.0",
    author="Vishnu Suresh Perumbavoor",
    author_email="vishnusureshperumbavoor@gmail.com",
    description="AI-powered chat agent about Vishnu Suresh Perumbavoor. Powered by Qwen2.5-0.5B.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/vishnusureshperumbavoor/vsp_bot",
    project_urls={
        "Bug Tracker": "https://github.com/vishnusureshperumbavoor/vsp_bot/issues",
        "LinkedIn": "https://www.linkedin.com/in/vishnu-suresh-perumbavoor/",
        "GitHub": "https://github.com/vishnusureshperumbavoor",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "transformers>=4.30.0",
        "torch>=2.0.0",
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "openai>=1.0.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "vspagent-py=vspagent.cli:main",
            # Alternative: "pyvspagent=vspagent.cli:main",
        ],
    },
    keywords="ai agent chatbot qwen llm vsp transformers",
)

