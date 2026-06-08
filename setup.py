from setuptools import setup, find_packages

setup(
    name="spotifydl",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "spotifydl": ["templates/*.html"],
    },
    install_requires=[
        "requests>=2.31.0",
        "spotipy>=2.23.0",
        "yt-dlp>=2023.11.16",
        "click>=8.1.7",
        "python-dotenv>=1.0.0",
        "mutagen",
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.27.0",
        "jinja2>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "spotifydl=spotifydl.cli:main",
        ],
    },
    author="Your Name",
    author_email="your.email@example.com",
    description="A tool to download music from Spotify links",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/spotifydl",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
) 
