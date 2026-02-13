# Installation

Follow these steps to install **Yoto Up**:


## Binary installation
Pre built binaries (Linux/Windows/MacOs) are provided for the flet based gui, these can be found under the "releases" section on github.

**Please note these binaries are unsigned and so may raise errors on a some platforms. Whilst they are built directly from the source code if this concerns you please run from source.**


## Installing from git

1. **Clone the repository:**

    ```bash
    git clone https://github.com/your-org/yoto-up.git
    cd yoto-up
    ```

2. **Create (and activate) virtual environment**
    ```bash
    uv venv
    source .venv/bin/activate
    ```


2. **Install dependencies:**
    ```bash
    uv pip install -r requirements.txt
    ```

3. **(Optional) Install GUI dependencies:**
    If you plan to use the GUI, install additional dependencies:
    ```bash
    uv pip install -r yoto_app/requirements.txt
    ```


4. **Start the application:**
    To start **Yoto Up**, you can use either CLI mode or GUI mode:

    - **CLI mode:**
        ```bash
        python yoto.py --help
        ```

    - **GUI mode:**
        ```bash
        python gui.py
        ``` 

## Next Steps

- See [Configuration](../configuration.md) for setup details.
- Visit [Troubleshooting](../troubleshooting.md) if you encounter issues.
