const { app, BrowserWindow, shell } = require('electron');

const STAFFORYX_URL = 'https://admin.poxelgraphic.com/';

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 700,
    title: 'Stafforyx HR',
    icon: `${__dirname}/assets/icon.ico`,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  window.loadURL(STAFFORYX_URL);

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(STAFFORYX_URL)) {
      return { action: 'allow' };
    }
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
