"""라이브 추출도 동영상과 같은 yt-dlp를 쓰되 취소 시 프로세스를 종료할 수 있게 한다."""


def main(args=None):
    import yt_dlp
    yt_dlp.main(args)


if __name__ == '__main__':
    main()
