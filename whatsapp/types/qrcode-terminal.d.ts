declare module 'qrcode-terminal' {
    interface QRCodeTerminalOptions {
        small?: boolean;
        scale?: number;
    }

    function generate(input: string, options?: QRCodeTerminalOptions, callback?: (qrcode: string) => void): void;

    const qrcodeTerminal: {
        generate: typeof generate;
    };

    export default qrcodeTerminal;
    export { generate };
}