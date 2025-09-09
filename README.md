# Yoto-UP

A multipurpose set of command-line, terminal UI, and graphical tools for managing your Yoto content.  

Features include content organization, device management, and easy integration with Yoto services.

## Features

- **Integration with Yoto Services**: Simplified access to Yoto's API and services.
- **Content Organization**: Easily manage and organize your Yoto cards and files.
   - Chapter and track management
   - Icon management
      - Autoselect icons or manually choose (via search)
   - Card export / import
   
- **Graphical and Terminal Interfaces**: Choose between a graphical interface or a terminal-based UI.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/yoto-up.git
   ```
2. Navigate to the project directory:
   ```bash
   cd yoto-up
   ```
3. Set up a virtual environment:
   ```bash
   uv venv
   source .venv/bin/activate
   ```
4. Install the required dependencies:
   ```bash
   uv pip install -r requirements.txt
   ```

## Usage

### Command-Line Interface (CLI) + Terminal UI (TUI)
Run the CLI tool:
```bash
python yoto.py
```

### Graphical Interface
Start the graphical interface:
```bash
python gui.py
```

## Contributing

1. Fork the repository.
2. Create a new branch:
   ```bash
   git checkout -b feature-branch-name
   ```
3. Commit your changes:
   ```bash
   git commit -m "Description of changes"
   ```
4. Push to the branch:
   ```bash
   git push origin feature-branch-name
   ```
5. Open a pull request.

## License

This project is licensed under the MIT license.

