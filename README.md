# ICT Streamlit Dashboard

## Project Overview
This project is a Streamlit dashboard designed to interact with multiple data sources, mainly focusing on the Fake data generator and SSH protocol. The dashboard provides an intuitive interface for visualizing and analyzing data.

## Setup Instructions
1. **Clone the repository**:
   ```bash
   git clone https://github.com/the-lizardking/ict-streamlit-dashboard.git
   cd ict-streamlit-dashboard
   ```
2. **Install the required dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the application**:
   ```bash
   streamlit run app.py
   ```

## How to Use Each Data Source
### Fake Data Source
- This data source simulates realistic data and is primarily used for testing purposes.
- To use it, simply select the "Fake Data" option in the dashboard. Customizable parameters allow you to generate user-defined datasets.

### SSH Data Source
- This functionality allows you to connect to a remote server via SSH to fetch live data.
- Provide your server credentials and specify the command to retrieve the required data in the dashboard. Always ensure to follow security best practices when handling SSH.

## Architecture Explanation
The dashboard is built using Streamlit, with a modular architecture:
- **Frontend**: Streamlit for creating the user interface.
- **Backend**: Python scripts handling data fetching and processing from both data sources.
- **Data Sources**: Initializes the Fake data generator and manages SSH connections for live data.

## Guidelines for AI Bots Editing the Repo
### Code Standards
- Follow PEP 8 style guide for Python code.
- Use meaningful variable names and comments for better readability.
- Ensure that all functions have docstrings explaining their purpose.
- Add type hints to function signatures for clarity.
- Keep functions small and focused on a single responsibility.

### Development Practices
- Always create a new branch for each feature or bug fix.
- Write clear and concise commit messages following conventional commits format.
- Test your changes locally before pushing to the remote repository.
- Open pull requests for review on significant changes.
- Maintain the existing code structure and module organization.
- Update documentation when adding new features or modifying existing functionality.

### File Structure Guidelines
- Keep data source implementations in data_sources.py.
- UI components and page logic should remain in app.py.
- Store environment variables in a .env file (never commit to repo).
- Add dependencies to requirements.txt when adding new packages.

## Conclusion
Feel free to explore the functionalities and experiment with different data sources in the ICT Streamlit Dashboard. If you encounter any issues or have suggestions, please open an issue in this repository!