from dify_plugin import Plugin
from dify_plugin.config.config import DifyPluginEnv

if __name__ == "__main__":
    plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=120))
    plugin.run()
