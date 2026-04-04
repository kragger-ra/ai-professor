# 4_Development

1. Prepare [installation](0_INSTALLATION.md) for all groups including dev group
2. Make changes
3. Make autoformat

    ```bash
    cd this_repo
    black src
    isort --profile=black src
    ```

4. Test changes in game
5. (Contributors) Make a new branch and PR
