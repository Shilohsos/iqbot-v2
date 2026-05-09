module.exports = {
  apps: [
    {
      name: 'iqbot-v2-bot',
      script: 'main_bot.py',
      interpreter: 'python3',
      cwd: '/root/iqbot-v2',
      autorestart: true,
      max_memory_restart: '500M',
      env: { NODE_ENV: 'production' },
    },
    {
      name: 'iqbot-v2-bias-engine',
      script: 'main_bias.py',
      interpreter: 'python3',
      cwd: '/root/iqbot-v2',
      autorestart: true,
      max_memory_restart: '500M',
    },
    {
      name: 'iqbot-v2-affiliate-listener',
      script: 'utils/affiliate_listener.py',
      interpreter: 'python3',
      cwd: '/root/iqbot-v2',
      autorestart: true,
    },
    // user watchers spawned dynamically via pm2_manager
  ]
};
